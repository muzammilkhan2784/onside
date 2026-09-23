"""football-data.org v4 - real fixtures, results and tables for current seasons.

Shallow compared with StatsBomb: scores, goals, cards and substitutions, but no
event stream, no coordinates and no xG. The adapter declares exactly that, and
the canonical events it produces carry only the fields the feed supplies -
never a location or an xG it did not send.

Free tier: 10 requests a minute, a dozen competitions, delayed scores. The
key is read from FOOTBALL_DATA_API_KEY; without one, only the unauthenticated
competition list is available and every other call raises a FeedError that
says so.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import settings
from ..domain.events import CanonicalEvent, PlayerRef, ShotDetail, TeamRef
from .base import CompetitionRef, FeedCapabilities, MatchRef
from .http import FeedClient

FEED = "football-data"
BASE_URL = "https://api.football-data.org/v4"

STATUS = {
    "SCHEDULED": "scheduled",
    "TIMED": "scheduled",
    "IN_PLAY": "live",
    "PAUSED": "half_time",
    "FINISHED": "finished",
    "AWARDED": "finished",
    "POSTPONED": "postponed",
    "SUSPENDED": "suspended",
    "CANCELLED": "cancelled",
}


#: football-data.org's official names, in the words people use for them. A
#: Spanish match labelled "Primera Division" reads as a different league from
#: the "La Liga" in the archive, and nobody searches for the official name.
NAMES = {
    "PD": "La Liga",
    "BSA": "Brasileirão",
    "CL": "Champions League",
    "EC": "European Championship",
    "WC": "World Cup",
    "CLI": "Copa Libertadores",
}


def competition_name(code: str, given: str) -> str:
    return NAMES.get(code, "") or given


class FootballDataAdapter:
    name = FEED

    def __init__(
        self, api_key: str | None = None, transport: httpx.BaseTransport | None = None
    ) -> None:
        key = settings().football_data_key if api_key is None else api_key
        self.client = FeedClient(
            BASE_URL, {"X-Auth-Token": key} if key else {}, per_minute=10, transport=transport
        )

    def capabilities(self) -> FeedCapabilities:
        return FeedCapabilities(
            name="football-data.org",
            has_events=False,
            has_xg=False,
            has_freeze_frames=False,
            has_lineups=False,
            has_corrections=False,
            is_live=True,
            update_seconds=60,
            licence="Free tier for non-commercial use; attribution requested.",
        )

    def list_competitions(self) -> list[CompetitionRef]:
        data = self.client.get("/competitions") or {}
        out = []
        for c in data.get("competitions", []):
            season = c.get("currentSeason") or {}
            out.append(
                CompetitionRef(
                    id=str(c["id"]),
                    name=competition_name(c.get("code", ""), c["name"]),
                    season_id=str(season.get("id", "")),
                    season_name=f"{season.get('startDate', '')[:4]}",
                )
            )
        return out

    def list_matches(self, competition_id: str, season_id: str) -> list[MatchRef]:
        data = (
            self.client.get(f"/competitions/{competition_id}/matches", {"season": season_id}) or {}
        )
        return [
            MatchRef(
                id=str(m["id"]),
                home=m["homeTeam"]["name"],
                away=m["awayTeam"]["name"],
                kickoff_utc=m.get("utcDate", ""),
                competition_id=competition_id,
                status=STATUS.get(m.get("status", ""), "scheduled"),
            )
            for m in data.get("matches", [])
        ]

    def fetch_match(self, match_id: str) -> dict[str, Any]:
        return self.client.get(f"/matches/{match_id}") or {}

    def fetch_events(self, match_id: str) -> list[CanonicalEvent]:
        m = self.fetch_match(match_id)
        return [self.normalise(raw, match_id) for raw in self._raw_events(m)]

    @staticmethod
    def _raw_events(m: dict[str, Any]) -> list[dict[str, Any]]:
        """Goals, bookings and substitutions flattened into one list, each
        tagged with its kind and the two teams for side resolution."""
        teams = {"home": m.get("homeTeam", {}), "away": m.get("awayTeam", {})}
        out: list[dict[str, Any]] = []
        for kind in ("goals", "bookings", "substitutions"):
            for i, item in enumerate(m.get(kind) or []):
                out.append({**item, "_kind": kind, "_i": i, "_teams": teams})
        out.sort(key=lambda e: (e.get("minute") or 0, e.get("injuryTime") or 0))
        return out

    def normalise(self, raw: dict[str, Any], match_id: str) -> CanonicalEvent:
        kind = raw["_kind"]
        team = raw.get("team") or {}
        minute = int(raw.get("minute") or 0)
        extra = int(raw.get("injuryTime") or 0)
        period = 1 if minute <= 45 else 2 if minute <= 90 else 3 if minute <= 105 else 4
        # Stable across fetches: the feed gives no event ids, so derive one from
        # what it does give. Same payload in, same id out.
        eid = f"fd-{match_id}-{kind}-{minute}-{extra}-{(raw.get('scorer') or raw.get('player') or raw.get('playerOut') or {}).get('id', raw['_i'])}"
        base: dict[str, Any] = {
            "event_id": eid,
            "match_id": match_id,
            "index": minute * 100 + extra,
            "period": period,
            "timestamp": "",
            "minute": minute + extra,
            "second": 0,
            "team": TeamRef(str(team.get("id", "")), team.get("name", "")) if team else None,
            "source_feed": FEED,
            "source_event_id": eid,
        }
        if kind == "goals":
            scorer = raw.get("scorer") or {}
            own = raw.get("type") == "OWN"
            return CanonicalEvent(
                **base,
                type="Own Goal Against" if own else "Shot",
                player=PlayerRef(str(scorer.get("id", "")), scorer.get("name", ""))
                if scorer
                else None,
                # xG absent, location absent: the feed does not send them.
                shot=None
                if own
                else ShotDetail(
                    outcome="Goal",
                    shot_type="Penalty" if raw.get("type") == "PENALTY" else "Open Play",
                ),
            )
        if kind == "bookings":
            p = raw.get("player") or {}
            card = {"YELLOW": "Yellow Card", "YELLOW_RED": "Second Yellow", "RED": "Red Card"}.get(
                raw.get("card", "")
            )
            return CanonicalEvent(
                **base,
                type="Bad Behaviour",
                player=PlayerRef(str(p.get("id", "")), p.get("name", "")) if p else None,
                card=card,
            )
        p_out, p_in = raw.get("playerOut") or {}, raw.get("playerIn") or {}
        return CanonicalEvent(
            **base,
            type="Substitution",
            player=PlayerRef(str(p_out.get("id", "")), p_out.get("name", "")) if p_out else None,
            substitution_replacement=PlayerRef(str(p_in.get("id", "")), p_in.get("name", ""))
            if p_in
            else None,
        )

    # ---- today's fixtures -------------------------------------------------
    def matches_between(self, date_from: str, date_to: str) -> list[dict[str, Any]]:
        """Every match in the plan's competitions between two dates (inclusive,
        YYYY-MM-DD), as display-ready fixture cards. One request, whatever the
        number of competitions - the free tier allows ten a minute."""
        data = self.client.get("/matches", {"dateFrom": date_from, "dateTo": date_to}) or {}
        return [fixture_card(m) for m in data.get("matches", [])]

    def matchday(self, code: str, matchday: int) -> list[dict[str, Any]]:
        """One round of a league - used for the round after an international
        break, which the date window cannot see yet."""
        data = self.client.get(f"/competitions/{code}/matches", {"matchday": matchday}) or {}
        return [fixture_card(m) for m in data.get("matches", [])]

    def current_competitions(self) -> list[dict[str, Any]]:
        """The plan's competitions with their current season - the menu for
        the live tables and scorers."""
        data = self.client.get("/competitions") or {}
        out = []
        for c in data.get("competitions", []):
            season = c.get("currentSeason") or {}
            out.append(
                {
                    "code": c.get("code", ""),
                    "id": str(c.get("id", "")),
                    "name": competition_name(c.get("code", ""), c.get("name", "")),
                    "type": c.get("type", ""),
                    "area": (c.get("area") or {}).get("name", ""),
                    "season": {
                        "start": season.get("startDate", ""),
                        "end": season.get("endDate", ""),
                        "matchday": season.get("currentMatchday"),
                    },
                }
            )
        return out

    def standings(self, code: str) -> dict[str, Any]:
        """The competition's current table(s): one per group or phase, totals only."""
        data = self.client.get(f"/competitions/{code}/standings") or {}
        tables = []
        for st in data.get("standings", []):
            if st.get("type") != "TOTAL":
                continue
            tables.append(
                {
                    "stage": (st.get("stage") or "").replace("_", " ").title(),
                    "group": st.get("group") or "",
                    "rows": [
                        {
                            "position": r.get("position"),
                            "team": _team(r.get("team") or {}),
                            "played": r.get("playedGames"),
                            "won": r.get("won"),
                            "drawn": r.get("draw"),
                            "lost": r.get("lost"),
                            "goalsFor": r.get("goalsFor"),
                            "goalsAgainst": r.get("goalsAgainst"),
                            "goalDifference": r.get("goalDifference"),
                            "points": r.get("points"),
                            "form": r.get("form"),
                        }
                        for r in st.get("table", [])
                    ],
                }
            )
        season = data.get("season") or {}
        return {"code": code, "matchday": season.get("currentMatchday"), "tables": tables}

    def scorers(self, code: str, limit: int = 20) -> dict[str, Any]:
        data = self.client.get(f"/competitions/{code}/scorers", {"limit": limit}) or {}
        return {
            "code": code,
            "rows": [
                {
                    "player": (s.get("player") or {}).get("name", ""),
                    "nationality": (s.get("player") or {}).get("nationality", ""),
                    "team": _team(s.get("team") or {}),
                    "played": s.get("playedMatches"),
                    "goals": s.get("goals") or 0,
                    "assists": s.get("assists"),
                    "penalties": s.get("penalties"),
                }
                for s in data.get("scorers", [])
            ],
        }


def _team(t: dict[str, Any]) -> dict[str, Any]:
    # The feed also offers badge images; Onside draws its own crests instead
    # (no licence for club badges), so the URL is deliberately not carried.
    return {
        "id": str(t.get("id", "")),
        "name": t.get("shortName") or t.get("name") or "TBC",
        "fullName": t.get("name") or "",
        "code": t.get("tla") or "",
    }


def fixture_card(m: dict[str, Any]) -> dict[str, Any]:
    """A football-data match as the fixture shape the web app renders. Only
    what the feed sends: no xG, no events, no invented minute."""
    comp = m.get("competition") or {}
    score = m.get("score") or {}
    full, half = score.get("fullTime") or {}, score.get("halfTime") or {}

    return {
        "id": f"fd-{m.get('id')}",
        "source": FEED,
        "competition": {
            "id": str(comp.get("id", "")),
            "name": competition_name(comp.get("code", ""), comp.get("name", "")),
            "code": comp.get("code", ""),
        },
        "kickoffUtc": m.get("utcDate", ""),
        "status": STATUS.get(m.get("status", ""), "scheduled"),
        "matchday": m.get("matchday"),
        "stage": (m.get("stage") or "").replace("_", " ").title(),
        "home": _team(m.get("homeTeam") or {}),
        "away": _team(m.get("awayTeam") or {}),
        "score": [full.get("home"), full.get("away")],
        "halfTime": [half.get("home"), half.get("away")],
    }
