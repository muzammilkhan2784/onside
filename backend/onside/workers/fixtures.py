"""Current football, from football-data.org.

The archive is history. This worker is the part of Onside that shows what is
happening now. Every minute it refreshes:

* the match window - the last three days of results and the next six days of
  fixtures, across every competition in the plan (one request);
* every ten minutes, the ten days after that (one request);
* after each competition-list refresh, the next round of each big league,
  one league a minute - the answer to "when are they back?" during an
  international break (one request);
* one competition's table, round-robin (one request);
* every other minute, one competition's top scorers (one request);
* every six hours, the competition list itself (one request).

That is at most five requests a minute against a free-tier budget of ten, so
a burst of retries never trips the limit. Everything lands in Redis for the
API; the API never calls the feed on a user's request.

Without FOOTBALL_DATA_API_KEY it does nothing but record that it is off, so
the web app can say so plainly instead of showing empty lists.

    python -m onside.workers.fixtures
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
from typing import Any

from ..config import settings
from ..feeds.football_data import FootballDataAdapter
from ..feeds.http import FeedError
from ..streams import bus

log = logging.getLogger("onside.fixtures")

KEY = "fixtures:today"
COMPETITIONS = "fd:competitions"
POLL_S = 60
PAST_DAYS, FUTURE_DAYS = 3, 6  # the feed allows at most a ten-day window
COMPETITIONS_EVERY_S = 6 * 3600
AHEAD_EVERY_TICKS = 10
BURST = ("PL", "PD", "BL1", "SA", "FL1")  # tables fetched at once on a cold start


def standings_key(code: str) -> str:
    return f"fd:standings:{code}"


def scorers_key(code: str) -> str:
    return f"fd:scorers:{code}"


def window(today: dt.date | None = None) -> tuple[str, str]:
    """Three days back to six days ahead, in UTC dates."""
    d = today or dt.datetime.now(dt.timezone.utc).date()
    return (
        (d - dt.timedelta(days=PAST_DAYS)).isoformat(),
        (d + dt.timedelta(days=FUTURE_DAYS)).isoformat(),
    )


def ahead_window(today: dt.date | None = None) -> tuple[str, str]:
    """The ten days after the main window."""
    d = today or dt.datetime.now(dt.timezone.utc).date()
    return (
        (d + dt.timedelta(days=FUTURE_DAYS + 1)).isoformat(),
        (d + dt.timedelta(days=FUTURE_DAYS + 10)).isoformat(),
    )


def snapshot(adapter: FootballDataAdapter, today: dt.date | None = None) -> dict[str, Any]:
    date_from, date_to = window(today)
    try:
        matches = adapter.matches_between(date_from, date_to)
    except FeedError as exc:
        return {"enabled": True, "ok": False, "message": str(exc), "matches": []}
    matches.sort(key=lambda m: (m["kickoffUtc"], m["competition"]["name"]))
    return {"enabled": True, "ok": True, "from": date_from, "to": date_to, "matches": matches}


def active(competitions: list[dict[str, Any]], today: dt.date | None = None) -> list[str]:
    """Codes of competitions whose current season is under way - no point
    polling a table for a tournament that finished last summer."""
    d = (today or dt.datetime.now(dt.timezone.utc).date()).isoformat()
    return [
        c["code"]
        for c in competitions
        if c["code"] and c["season"]["start"] <= d <= (c["season"]["end"] or "9999")
    ]


def _put(r: Any, key: str, body: dict[str, Any] | list[Any]) -> None:
    """Store with the time it was fetched; lists are wrapped as {"data": [...]}."""
    payload = {**body} if isinstance(body, dict) else {"data": body}
    payload["fetchedAt"] = time.time()
    r.set(key, json.dumps(payload, separators=(",", ":")))


def publish(r: Any, body: dict[str, Any]) -> None:
    _put(r, KEY, body)


STATE = "fd:poller"


class Poller:
    """One tick a minute, each spending at most five requests.

    Its memory - where it is in the rotations, the far window, the next rounds
    - lives in the store, not in the process, so a Lambda that starts cold
    carries on exactly where the last invocation stopped."""

    def __init__(self, adapter: FootballDataAdapter, r: Any) -> None:
        self.adapter, self.r = adapter, r
        self.codes: list[str] = []
        self.competitions_at = 0.0
        self.tick_n = 0
        self.ahead: list[dict[str, Any]] = []
        self.ahead_to = ""
        self.next_rounds: dict[str, list[dict[str, Any]]] = {}
        self.round_queue: list[tuple[str, int]] = []
        self._restore()

    def _restore(self) -> None:
        raw = self.r.get(STATE)
        if not raw:
            return
        st = json.loads(raw)
        self.tick_n = st.get("tick", 0)
        self.codes = st.get("codes", [])
        self.competitions_at = st.get("competitionsAt", 0.0)
        self.ahead = st.get("ahead", [])
        self.ahead_to = st.get("aheadTo", "")
        self.next_rounds = st.get("nextRounds", {})
        self.round_queue = [(c, int(md)) for c, md in st.get("roundQueue", [])]

    def _persist(self) -> None:
        state = {
            "tick": self.tick_n,
            "codes": self.codes,
            "competitionsAt": self.competitions_at,
            "ahead": self.ahead,
            "aheadTo": self.ahead_to,
            "nextRounds": self.next_rounds,
            "roundQueue": self.round_queue,
        }
        self.r.set(STATE, json.dumps(state, separators=(",", ":")))

    def tick(self) -> dict[str, Any]:
        body = snapshot(self.adapter)
        if not body["ok"]:
            last = json.loads(self.r.get(KEY) or "{}")
            if not last.get("ok"):
                publish(self.r, body)
            # Otherwise one failed request (a timeout, a rate limit) leaves the
            # last good fixtures in place. Their `fetchedAt` stays old, so the
            # API marks them stale after five minutes rather than blanking them.
            return body
        if self.tick_n % AHEAD_EVERY_TICKS == 0:
            date_from, date_to = ahead_window()
            try:
                self.ahead = self.adapter.matches_between(date_from, date_to)
                self.ahead_to = date_to
            except FeedError as exc:
                log.warning("ahead window: %s", exc)
        if self.round_queue:
            code, md = self.round_queue.pop(0)
            try:
                self.next_rounds[code] = self.adapter.matchday(code, md)
            except FeedError as exc:
                log.warning("next round of %s: %s", code, exc)
        seen = {m["id"] for m in body["matches"]}
        for extra in (self.ahead, *self.next_rounds.values()):
            for m in extra:
                if m["id"] not in seen:
                    seen.add(m["id"])
                    body["matches"].append(m)
        body["matches"].sort(key=lambda m: (m["kickoffUtc"], m["competition"]["name"]))
        body["to"] = self.ahead_to or body["to"]
        publish(self.r, body)
        if time.time() - self.competitions_at > COMPETITIONS_EVERY_S or not self.codes:
            try:
                comps = self.adapter.current_competitions()
                _put(self.r, COMPETITIONS, comps)
                self.codes = active(comps)
                self.competitions_at = time.time()
                self.round_queue = sorted(
                    (
                        (c["code"], c["season"]["matchday"] + 1)
                        for c in comps
                        if c["code"] in BURST
                        and c["code"] in self.codes
                        and c["season"]["matchday"]
                    ),
                    key=lambda cm: BURST.index(cm[0]),  # biggest league first
                )
            except FeedError as exc:
                log.warning("competitions: %s", exc)
        if self.codes and self.tick_n == 0:
            # Cold start: the big five tables at once, so the home page has
            # them in seconds rather than after a round of the rotation.
            for code in (c for c in BURST if c in self.codes):
                self._refresh(standings_key(code), lambda code=code: self.adapter.standings(code))
        elif self.codes:
            code = self.codes[self.tick_n % len(self.codes)]
            self._refresh(standings_key(code), lambda: self.adapter.standings(code))
            if self.tick_n % 2 == 0:
                code = self.codes[(self.tick_n // 2) % len(self.codes)]
                self._refresh(scorers_key(code), lambda: self.adapter.scorers(code))
        self.tick_n += 1
        self._persist()
        return body

    def _refresh(self, key: str, fetch: Any) -> None:
        try:
            _put(self.r, key, fetch())
        except FeedError as exc:
            log.warning("%s: %s", key, exc)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per cycle, not per request
    r = bus.sync_client()
    if not settings().football_data_key:
        publish(r, {"enabled": False, "matches": []})
        log.info("FOOTBALL_DATA_API_KEY is not set; current fixtures are off.")
        while True:  # stay up so the container is healthy; nothing to do
            time.sleep(3600)
    poller = Poller(FootballDataAdapter(), r)
    while True:
        started = time.time()
        body = poller.tick()
        log.info(
            "fixtures: %s", f"{len(body['matches'])} matches" if body["ok"] else body["message"]
        )
        time.sleep(max(1.0, POLL_S - (time.time() - started)))


if __name__ == "__main__":
    main()
