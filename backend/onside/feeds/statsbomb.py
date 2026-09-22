"""StatsBomb -> canonical events.

StatsBomb is the deepest public taxonomy, so Onside's canonical model follows
it and everything else normalises inward. The mapping is still explicit rather
than a blind dict copy, because the rule in SPEC.md section 12.2 is absolute:
where a feed is shallower the field is *absent*, never invented.
"""

from __future__ import annotations

from typing import Any

from ..domain.events import (
    CanonicalEvent,
    FreezeFrameActor,
    PassDetail,
    PlayerRef,
    ShotDetail,
    TeamRef,
)
from .base import CompetitionRef, FeedCapabilities, MatchRef

FEED = "statsbomb"


def _ref(obj: dict[str, Any] | None) -> dict[str, Any] | None:
    return obj if isinstance(obj, dict) else None


def _team(obj: dict[str, Any] | None) -> TeamRef | None:
    o = _ref(obj)
    return TeamRef(str(o["id"]), o["name"]) if o else None


def _player(obj: dict[str, Any] | None) -> PlayerRef | None:
    o = _ref(obj)
    return PlayerRef(str(o["id"]), o["name"]) if o else None


def _name(obj: Any) -> str:
    return obj["name"] if isinstance(obj, dict) and "name" in obj else ""


def _loc(raw: Any) -> tuple[float, float] | None:
    if isinstance(raw, list) and len(raw) >= 2:
        return (float(raw[0]), float(raw[1]))
    return None


def _shot(raw: dict[str, Any]) -> ShotDetail:
    ff = []
    for actor in raw.get("freeze_frame") or []:
        loc = _loc(actor.get("location"))
        if loc is None:
            continue
        ff.append(
            FreezeFrameActor(
                x=loc[0],
                y=loc[1],
                teammate=bool(actor.get("teammate")),
                keeper=_name(actor.get("position")) == "Goalkeeper",
                name=_name(actor.get("player")) or (actor.get("player") or {}).get("name", ""),
            )
        )
    end = raw.get("end_location") or []
    return ShotDetail(
        xg=raw.get("statsbomb_xg"),
        outcome=_name(raw.get("outcome")),
        shot_type=_name(raw.get("type")),
        body_part=_name(raw.get("body_part")),
        technique=_name(raw.get("technique")),
        end_location=tuple(float(v) for v in end) if isinstance(end, list) else (),
        freeze_frame=tuple(ff),
        key_pass_id=raw.get("key_pass_id"),
        first_time=bool(raw.get("first_time")),
        one_on_one=bool(raw.get("one_on_one")),
    )


def _pass(raw: dict[str, Any]) -> PassDetail:
    end = raw.get("end_location") or []
    return PassDetail(
        recipient=_player(raw.get("recipient")),
        length=raw.get("length"),
        angle=raw.get("angle"),
        height=_name(raw.get("height")),
        end_location=tuple(float(v) for v in end) if isinstance(end, list) else (),
        body_part=_name(raw.get("body_part")),
        pass_type=_name(raw.get("type")),
        outcome=_name(raw.get("outcome")),
        technique=_name(raw.get("technique")),
        cross=bool(raw.get("cross")),
        cut_back=bool(raw.get("cut_back")),
        switch=bool(raw.get("switch")),
        through_ball=bool(raw.get("through_ball")),
        shot_assist=bool(raw.get("shot_assist")),
        goal_assist=bool(raw.get("goal_assist")),
    )


def _card(raw: dict[str, Any]) -> str | None:
    """A card can arrive on a foul or on bad behaviour. Both mean the same."""
    for key in ("foul_committed", "bad_behaviour"):
        block = raw.get(key)
        if isinstance(block, dict) and block.get("card"):
            return _name(block["card"])
    return None


def normalise(
    raw: dict[str, Any], match_id: str, nicknames: dict[str, str] | None = None
) -> CanonicalEvent:
    """One raw StatsBomb event -> one canonical event.

    `nicknames` maps player id to the name a broadcaster would use. StatsBomb
    records full legal names - "Lionel Andres Messi Cuccittini" - which are
    correct and unreadable in a match report.
    """

    def named(ref: PlayerRef | None) -> PlayerRef | None:
        if ref is None or not nicknames:
            return ref
        nick = nicknames.get(ref.id)
        return PlayerRef(ref.id, nick) if nick else ref

    shot_raw = raw.get("shot")
    pass_raw = raw.get("pass")
    sub_raw = raw.get("substitution")

    return CanonicalEvent(
        event_id=raw["id"],
        match_id=match_id,
        index=int(raw.get("index", 0)),
        period=int(raw.get("period", 1)),
        timestamp=raw.get("timestamp", "00:00:00.000"),
        minute=int(raw.get("minute", 0)),
        second=int(raw.get("second", 0)),
        type=_name(raw.get("type")),
        team=_team(raw.get("team")),
        player=named(_player(raw.get("player"))),
        position=_name(raw.get("position")),
        possession=int(raw.get("possession", 0)),
        possession_team=_team(raw.get("possession_team")),
        play_pattern=_name(raw.get("play_pattern")),
        location=_loc(raw.get("location")),
        duration=raw.get("duration"),
        under_pressure=bool(raw.get("under_pressure")),
        counterpress=bool(raw.get("counterpress")),
        out=bool(raw.get("out")),
        related_events=tuple(raw.get("related_events") or ()),
        shot=_shot(shot_raw) if isinstance(shot_raw, dict) else None,
        pass_=_pass(pass_raw) if isinstance(pass_raw, dict) else None,
        card=_card(raw),
        duel_type=_name((raw.get("duel") or {}).get("type")),
        substitution_replacement=named(_player((sub_raw or {}).get("replacement")))
        if sub_raw
        else None,
        tactics=raw.get("tactics"),
        source_feed=FEED,
        source_event_id=raw["id"],
    )


def normalise_match(
    raw_events: list[dict[str, Any]],
    match_id: str,
    nicknames: dict[str, str] | None = None,
) -> list[CanonicalEvent]:
    return [normalise(e, match_id, nicknames) for e in raw_events]


class StatsBombAdapter:
    """The deep historical feed: every event, with xG and 360 freeze-frames.

    Deliberately declares `is_live=False` and `has_corrections=False`. It is
    the deepest feed Onside has and it still cannot do the one thing the
    project is named for, which is exactly why the adapter layer exists.
    """

    name = FEED

    def __init__(self, nicknames: dict[str, str] | None = None) -> None:
        self._nicknames = nicknames or {}

    def capabilities(self) -> FeedCapabilities:
        return FeedCapabilities(
            name="StatsBomb Open Data",
            has_events=True,
            has_xg=True,
            has_freeze_frames=True,
            has_lineups=True,
            has_corrections=False,  # open data records no VAR decisions
            is_live=False,
            update_seconds=None,
            licence="Free for research and education; credit required.",
        )

    def list_competitions(self) -> list[CompetitionRef]:
        from ..replay.download import BASE, CACHE, _get

        out = []
        for c in _get(f"{BASE}/competitions.json", CACHE / "competitions.json"):
            out.append(
                CompetitionRef(
                    id=str(c["competition_id"]),
                    name=c["competition_name"],
                    season_id=str(c["season_id"]),
                    season_name=c["season_name"],
                )
            )
        return out

    def list_matches(self, competition_id: str, season_id: str) -> list[MatchRef]:
        from ..replay.download import fetch_matches

        return [
            MatchRef(
                id=str(m["match_id"]),
                home=m["home_team"]["home_team_name"],
                away=m["away_team"]["away_team_name"],
                kickoff_utc=f"{m.get('match_date', '')}T{m.get('kick_off') or '00:00:00.000'}",
                competition_id=competition_id,
                status="finished",
            )
            for m in fetch_matches(int(competition_id), int(season_id))
        ]

    def fetch_events(self, match_id: str) -> list[CanonicalEvent]:
        from ..replay.download import fetch_events, nickname_map

        nicks = self._nicknames or nickname_map(int(match_id))
        return normalise_match(fetch_events(int(match_id)), match_id, nicks)

    def normalise(self, raw: dict[str, Any], match_id: str) -> CanonicalEvent:
        return normalise(raw, match_id, self._nicknames)
