"""Canonical events and corrections <-> plain dicts, for the event log.

The domain layer is dataclasses with no serialisation concerns. This module is
the one place that knows how a `CanonicalEvent` becomes bytes and comes back,
and `tests/unit/test_codec.py` round-trips a whole real match through it.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..domain.corrections import Correction
from ..domain.events import (
    CanonicalEvent,
    FreezeFrameActor,
    PassDetail,
    PlayerRef,
    ShotDetail,
    TeamRef,
)


def event_to_dict(e: CanonicalEvent) -> dict[str, Any]:
    d = asdict(e)
    d["extra"] = {}
    return d


def _team(d: dict[str, Any] | None) -> TeamRef | None:
    return TeamRef(**d) if d else None


def _player(d: dict[str, Any] | None) -> PlayerRef | None:
    return PlayerRef(**d) if d else None


def event_from_dict(d: dict[str, Any]) -> CanonicalEvent:
    shot = d.get("shot")
    pass_ = d.get("pass_")
    return CanonicalEvent(
        event_id=d["event_id"],
        match_id=d["match_id"],
        index=d["index"],
        period=d["period"],
        timestamp=d["timestamp"],
        minute=d["minute"],
        second=d["second"],
        type=d["type"],
        team=_team(d.get("team")),
        player=_player(d.get("player")),
        position=d.get("position", ""),
        possession=d.get("possession", 0),
        possession_team=_team(d.get("possession_team")),
        play_pattern=d.get("play_pattern", ""),
        location=tuple(d["location"]) if d.get("location") else None,  # type: ignore[arg-type]
        duration=d.get("duration"),
        under_pressure=d.get("under_pressure", False),
        counterpress=d.get("counterpress", False),
        out=d.get("out", False),
        related_events=tuple(d.get("related_events") or ()),
        shot=ShotDetail(
            **{
                **shot,
                "end_location": tuple(shot.get("end_location") or ()),
                "freeze_frame": tuple(
                    FreezeFrameActor(**a) for a in shot.get("freeze_frame") or ()
                ),
            }
        )
        if shot
        else None,
        pass_=PassDetail(
            **{
                **pass_,
                "recipient": _player(pass_.get("recipient")),
                "end_location": tuple(pass_.get("end_location") or ()),
            }
        )
        if pass_
        else None,
        card=d.get("card"),
        duel_type=d.get("duel_type", ""),
        substitution_replacement=_player(d.get("substitution_replacement")),
        tactics=d.get("tactics"),
        source_feed=d.get("source_feed", ""),
        source_event_id=d.get("source_event_id", ""),
    )


def correction_to_dict(c: Correction) -> dict[str, Any]:
    return asdict(c)


def correction_from_dict(d: dict[str, Any]) -> Correction:
    return Correction(**d)
