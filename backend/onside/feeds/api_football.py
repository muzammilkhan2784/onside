"""API-Football v3 - global live coverage, 1,200+ leagues, 15-second updates.

Implemented and contract-tested, deliberately not enabled: it needs a paid key
for anything beyond 100 requests a day. Enabling it is configuration
(API_FOOTBALL_KEY) and a subscription, not a rewrite - which is the point of
the adapter layer.

It is also the one feed here that reports VAR decisions: its event stream
includes `type: "Var"` entries such as "Goal cancelled" and "Penalty
confirmed". A cancelled goal is normalised into a real `disallow` Correction
superseding the goal it cancels - the thing StatsBomb's open data cannot
supply, and the reason the correction pipeline exists.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx

from ..config import settings
from ..domain.corrections import Correction
from ..domain.events import CanonicalEvent, PlayerRef, ShotDetail, TeamRef
from .base import CompetitionRef, FeedCapabilities, MatchRef
from .http import FeedClient

FEED = "api-football"
BASE_URL = "https://v3.football.api-sports.io"
POLL_SECONDS = 15


class ApiFootballAdapter:
    name = FEED

    def __init__(
        self, api_key: str | None = None, transport: httpx.BaseTransport | None = None
    ) -> None:
        key = settings().api_football_key if api_key is None else api_key
        self.client = FeedClient(
            BASE_URL, {"x-apisports-key": key} if key else {}, per_minute=30, transport=transport
        )

    def capabilities(self) -> FeedCapabilities:
        return FeedCapabilities(
            name="API-Football",
            has_events=True,
            has_xg=False,
            has_freeze_frames=False,
            has_lineups=True,
            has_corrections=True,
            is_live=True,
            update_seconds=POLL_SECONDS,
            licence="Commercial API; free tier 100 requests a day.",
        )

    def list_competitions(self) -> list[CompetitionRef]:
        data = self.client.get("/leagues", {"current": "true"}) or {}
        out = []
        for row in data.get("response", []):
            lg, seasons = row["league"], row.get("seasons") or []
            cur = next((s for s in seasons if s.get("current")), seasons[-1] if seasons else {})
            out.append(
                CompetitionRef(
                    id=str(lg["id"]),
                    name=lg["name"],
                    season_id=str(cur.get("year", "")),
                    season_name=str(cur.get("year", "")),
                )
            )
        return out

    def list_matches(self, competition_id: str, season_id: str) -> list[MatchRef]:
        data = self.client.get("/fixtures", {"league": competition_id, "season": season_id}) or {}
        out = []
        for row in data.get("response", []):
            f, t = row["fixture"], row["teams"]
            out.append(
                MatchRef(
                    id=str(f["id"]),
                    home=t["home"]["name"],
                    away=t["away"]["name"],
                    kickoff_utc=f.get("date", ""),
                    competition_id=competition_id,
                    status=_status(f.get("status", {}).get("short", "")),
                )
            )
        return out

    def raw_events(self, match_id: str) -> list[dict[str, Any]]:
        data = self.client.get("/fixtures/events", {"fixture": match_id}) or {}
        return list(data.get("response", []))

    def fetch_events(self, match_id: str) -> list[CanonicalEvent]:
        return [
            n
            for n in self.normalise_all(self.raw_events(match_id), match_id)
            if isinstance(n, CanonicalEvent)
        ]

    def normalise_all(
        self, raws: list[dict[str, Any]], match_id: str
    ) -> list[CanonicalEvent | Correction]:
        """Normalise a whole event list. VAR entries need context - the goal a
        "Goal cancelled" supersedes is the latest goal by that team at or
        before its minute - so they are resolved here, not one at a time."""
        out: list[CanonicalEvent | Correction] = []
        goals: list[CanonicalEvent] = []
        for i, raw in enumerate(raws):
            if raw.get("type") == "Var":
                corr = self._var(raw, i, match_id, goals)
                if corr is not None:
                    out.append(corr)
                continue
            e = self.normalise({**raw, "_i": i}, match_id)
            if e.is_goal:
                goals.append(e)
            out.append(e)
        return out

    def normalise(self, raw: dict[str, Any], match_id: str) -> CanonicalEvent:
        t = raw.get("time") or {}
        minute = int(t.get("elapsed") or 0)
        extra = int(t.get("extra") or 0)
        period = 1 if minute <= 45 else 2 if minute <= 90 else 3 if minute <= 105 else 4
        team, player = raw.get("team") or {}, raw.get("player") or {}
        kind, detail = raw.get("type", ""), raw.get("detail", "")
        eid = f"af-{match_id}-{raw.get('_i', 0)}-{kind}-{minute}-{player.get('id', '')}"
        base: dict[str, Any] = {
            "event_id": eid,
            "match_id": match_id,
            "index": int(raw.get("_i", 0)),
            "period": period,
            "timestamp": "",
            "minute": minute + extra,
            "second": 0,
            "team": TeamRef(str(team.get("id", "")), team.get("name", "")) if team else None,
            "player": PlayerRef(str(player.get("id", "")), player.get("name", ""))
            if player.get("id")
            else None,
            "source_feed": FEED,
            "source_event_id": eid,
        }
        if kind == "Goal":
            if detail == "Own Goal":
                return CanonicalEvent(**base, type="Own Goal Against")
            outcome = "Missed" if detail == "Missed Penalty" else "Goal"
            return CanonicalEvent(
                **base,
                type="Shot",
                shot=ShotDetail(
                    outcome=outcome, shot_type="Penalty" if "Penalty" in detail else "Open Play"
                ),
            )
        if kind == "Card":
            card = {
                "Yellow Card": "Yellow Card",
                "Red Card": "Red Card",
                "Second Yellow card": "Second Yellow",
            }.get(detail)
            return CanonicalEvent(**base, type="Bad Behaviour", card=card)
        if kind == "subst":
            assist = raw.get("assist") or {}
            return CanonicalEvent(
                **base,
                type="Substitution",
                substitution_replacement=PlayerRef(
                    str(assist.get("id", "")), assist.get("name", "")
                )
                if assist.get("id")
                else None,
            )
        return CanonicalEvent(**base, type=kind or "Unknown")

    @staticmethod
    def _var(
        raw: dict[str, Any], i: int, match_id: str, goals: list[CanonicalEvent]
    ) -> Correction | None:
        detail = (raw.get("detail") or "").lower()
        if "goal cancelled" not in detail and "goal disallowed" not in detail:
            return None  # "Penalty confirmed" etc. change nothing in the log
        t = raw.get("time") or {}
        minute = int(t.get("elapsed") or 0) + int(t.get("extra") or 0)
        team_id = str((raw.get("team") or {}).get("id", ""))
        candidates = [g for g in goals if g.team and g.team.id == team_id and g.minute <= minute]
        if not candidates:
            return None
        target = candidates[-1]
        return Correction(
            correction_id=f"af-var-{match_id}-{i}",
            match_id=match_id,
            supersedes=target.event_id,
            kind="disallow",
            reason=raw.get("comments") or raw.get("detail") or "Goal cancelled by VAR",
            authority="VAR",
            period=target.period,
            decided_at_minute=max(minute, target.minute),
            synthesised=False,
        )

    def stream_events(
        self, match_id: str, stop_after: float | None = None
    ) -> Iterator[CanonicalEvent | Correction]:
        """Poll the fixture and yield only what is new since the last poll.
        Event and correction ids are stable, so the log's idempotent append
        absorbs any overlap between polls."""
        seen: set[str] = set()
        started = time.monotonic()
        while stop_after is None or time.monotonic() - started < stop_after:
            for rec in self.normalise_all(self.raw_events(match_id), match_id):
                key = rec.correction_id if isinstance(rec, Correction) else rec.event_id
                if key not in seen:
                    seen.add(key)
                    yield rec
            time.sleep(POLL_SECONDS)


def _status(short: str) -> str:
    if short in ("1H", "2H", "ET", "P", "LIVE", "BT"):
        return "live"
    if short == "HT":
        return "half_time"
    if short in ("FT", "AET", "PEN"):
        return "finished"
    return "scheduled"
