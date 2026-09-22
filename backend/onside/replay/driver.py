"""Replay an archived match as if it were live.

The demo, the manual test harness and the load driver in one. A replayed match
gets its own id (`live-<match id>`), so replaying the 2022 final with an
injected VAR check never alters the archive's true record of that match.

    python -m onside.replay.driver --match 3869685 --speed 30 --inject-var
    python -m onside.replay.driver --serve --autostart 3869685 --loop

In `--serve` mode it also takes start/pause/resume/stop commands from the
`replay:control` stream, which is what the API's /api/replay endpoints write to.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import threading
import time
from typing import Any

import redis

from ..domain.events import CanonicalEvent
from ..feeds.statsbomb import normalise_match
from ..ingest.build import causal_elo, match_index
from ..store import codec, repo
from ..streams import bus
from . import build_timeline
from .download import fetch_events, fetch_lineups
from .var_injector import DISCLAIMER, inject

log = logging.getLogger("onside.replay")

TICK_S = 0.1


def live_id(match_id: int | str) -> str:
    return f"live-{match_id}"


def state_key(lid: str) -> str:
    return f"replay:state:{lid}"


_INDEX: dict[int, dict[str, Any]] = {}
_ELO: dict[int, float] = {}


def _meta(match_id: int) -> dict[str, Any]:
    if not _INDEX:
        idx = match_index()
        _INDEX.update({m["match_id"]: m for m in idx})
        _ELO.update(causal_elo(idx))
    return _INDEX[match_id]


class Replay:
    """One replaying match. Runs in its own thread."""

    def __init__(
        self,
        match_id: int,
        speed: float,
        inject_var: bool,
        loop: bool,
        r: redis.Redis | None = None,
    ) -> None:
        self.match_id = match_id
        self.lid = live_id(match_id)
        self.speed = max(speed, 0.1)
        self.inject_var = inject_var
        self.loop = loop
        self.r = r or bus.sync_client()
        self.thread: threading.Thread | None = None

    # ---- setup ------------------------------------------------------------
    def _prepare(self) -> list[build_timeline.Scheduled]:
        meta = dict(_meta(self.match_id))
        lineups = fetch_lineups(self.match_id)
        nick = {
            str(p["player_id"]): p["player_nickname"]
            for t in lineups
            for p in t.get("lineup", [])
            if p.get("player_nickname")
        }
        raw = fetch_events(self.match_id)
        # Re-key every event to the live id. The event ids themselves stay the
        # real StatsBomb ids, so provenance survives the replay.
        events: list[CanonicalEvent] = [
            dataclasses.replace(e, match_id=self.lid) for e in normalise_match(raw, self.lid, nick)
        ]
        corrections = (
            inject(
                events, match_id=self.lid, disallow=1, amend=1, target_event_id=self._target(events)
            )
            if self.inject_var
            else []
        )

        meta["match_id"] = self.lid
        meta["_elo_diff"] = _ELO.get(self.match_id, 0.0)
        meta["_replay"] = {
            "of": str(self.match_id),
            "speed": self.speed,
            "injectedVar": self.inject_var,
            "disclaimer": DISCLAIMER if self.inject_var else "",
        }
        self.r.set(f"live:meta:{self.lid}", json.dumps(meta))
        self.r.set(f"live:lineups:{self.lid}", json.dumps(lineups))

        # A restarted replay is a new history for a demo id, so its log and
        # projection are cleared. The archived match is never touched.
        repo.clear_log(self.lid)
        repo.delete_match(self.lid)
        # Tell the shard owner to drop its in-memory copy of the old history.
        bus.produce("control", self.lid, {"action": "reset"}, self.r)
        bus.publish(bus.channel(self.lid), {"type": "replay_restarted", "matchId": self.lid})
        self.r.sadd(bus.ACTIVE_REPLAYS, self.lid)
        return build_timeline.build(events, corrections)

    @staticmethod
    def _target(events: list[CanonicalEvent]) -> str | None:
        goals = [e for e in events if e.is_goal and e.period <= 2]
        return goals[1].event_id if len(goals) > 1 else (goals[0].event_id if goals else None)

    # ---- control ----------------------------------------------------------
    def _status(self, **fields: Any) -> None:
        fields["heartbeat"] = time.time()
        self.r.hset(state_key(self.lid), mapping={k: str(v) for k, v in fields.items()})

    def _command(self) -> str:
        return str(self.r.hget(state_key(self.lid), "command") or "")

    # ---- run --------------------------------------------------------------
    def run(self) -> None:
        while True:
            schedule = self._prepare()
            total = len(schedule)
            home, away = (
                _meta(self.match_id)["home_team"]["home_team_name"],
                _meta(self.match_id)["away_team"]["away_team_name"],
            )
            self._status(
                status="running",
                command="",
                speed=self.speed,
                sent=0,
                total=total,
                matchId=self.lid,
                of=self.match_id,
                title=f"{home} v {away}",
                minute=0,
            )
            clock = 0.0
            i = 0
            last_report = time.time()
            wall = time.time()
            while i < total:
                cmd = self._command()
                if cmd == "stop":
                    self._status(status="stopped", command="")
                    return
                if cmd == "pause":
                    self._status(status="paused")
                    time.sleep(TICK_S)
                    wall = time.time()
                    continue
                speed_raw = self.r.hget(state_key(self.lid), "speed")
                self.speed = float(speed_raw) if speed_raw else self.speed
                now = time.time()
                clock += (now - wall) * self.speed
                wall = now
                pipe = self.r.pipeline(transaction=False)
                while i < total and schedule[i].at <= clock:
                    s = schedule[i]
                    body = (
                        codec.event_to_dict(s.record)
                        if s.kind == "event"  # type: ignore[arg-type]
                        else codec.correction_to_dict(s.record)
                    )  # type: ignore[arg-type]
                    pipe.xadd(
                        bus.stream_for(self.lid),
                        {
                            "kind": s.kind,
                            "match": self.lid,
                            "body": json.dumps(body, separators=(",", ":")),
                        },
                        maxlen=200_000,
                        approximate=True,
                    )
                    i += 1
                pipe.execute()
                minute = int(clock // 60)
                self._status(status="running", sent=i, minute=minute)
                if time.time() - last_report > 5:
                    left = (schedule[-1].at - clock) / self.speed
                    log.info(
                        "Replaying %s v %s at %gx - %s of %s events sent, about %.0f seconds remaining",
                        home,
                        away,
                        self.speed,
                        f"{i:,}",
                        f"{total:,}",
                        max(left, 0),
                    )
                    last_report = time.time()
                time.sleep(TICK_S)
            self._status(status="finished", sent=total)
            log.info("Replay of %s v %s finished.", home, away)
            if not self.loop:
                return
            time.sleep(30)  # let people see full time before it starts again

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run, name=f"replay-{self.lid}", daemon=True)
        self.thread.start()


def serve(autostart: list[int], speed: float, inject_var: bool, loop: bool) -> None:
    r = bus.sync_client()
    # The control loop blocks on XREAD; give it its own connection so a replay
    # thread's traffic can never sit between it and its reply.
    control = redis.Redis.from_url(
        bus.settings().redis_url,
        decode_responses=True,
        socket_timeout=None,
        health_check_interval=30,
    )
    running: dict[str, Replay] = {}
    # Replays recorded as playing by a previous process are not playing now:
    # their threads died with it. Say so rather than show a frozen "live" match.
    for lid in r.smembers(bus.ACTIVE_REPLAYS):  # type: ignore[union-attr]
        if r.hget(state_key(lid), "status") in bus.PLAYING:
            r.hset(state_key(lid), mapping={"status": "stopped", "command": ""})
    for mid in autostart:
        rp = Replay(mid, speed, inject_var, loop, r)
        rp.start()
        running[rp.lid] = rp
    last = "$"
    log.info("replay service listening on %s", bus.REPLAY_CONTROL_STREAM)
    while True:
        try:
            resp = control.xread({bus.REPLAY_CONTROL_STREAM: last}, block=5000, count=10)
        except (redis.ConnectionError, redis.TimeoutError):
            log.warning("control stream unavailable; retrying")
            time.sleep(1)
            continue
        for _stream, entries in resp or []:
            for entry_id, fields in entries:
                last = entry_id
                if fields.get("command") != "start":
                    continue
                mid = int(fields["match"])
                lid = live_id(mid)
                existing = running.get(lid)
                if existing and existing.thread and existing.thread.is_alive():
                    r.hset(state_key(lid), mapping={"command": "stop"})
                    existing.thread.join(timeout=5)
                rp = Replay(
                    mid,
                    float(fields.get("speed", speed)),
                    fields.get("inject_var", "1") == "1",
                    False,
                    r,
                )
                rp.start()
                running[lid] = rp


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--match", type=int, default=3869685)
    ap.add_argument("--speed", type=float, default=30.0, help="match-seconds per real second")
    ap.add_argument("--inject-var", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--autostart", type=int, nargs="*", default=[])
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if args.serve:
        serve(args.autostart, args.speed, args.inject_var, args.loop)
    else:
        Replay(args.match, args.speed, args.inject_var, args.loop).run()


if __name__ == "__main__":
    main()
