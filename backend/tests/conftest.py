from __future__ import annotations

import itertools

import pytest

from onside.domain.corrections import Correction
from onside.domain.events import CanonicalEvent, PlayerRef, ShotDetail, TeamRef

HOME = TeamRef("1", "Argentina")
AWAY = TeamRef("2", "France")

_counter = itertools.count(1)


def ev(
    *,
    minute: int,
    type: str = "Pass",
    team: TeamRef = HOME,
    player: str = "A Player",
    goal: bool = False,
    xg: float | None = None,
    shot_type: str = "Open Play",
    card: str | None = None,
    period: int = 1,
    second: int = 0,
    event_id: str | None = None,
    index: int | None = None,
) -> CanonicalEvent:
    """A minimal canonical event, for tests that care about one field."""
    n = next(_counter)
    shot = None
    if goal or xg is not None:
        shot = ShotDetail(xg=xg, outcome="Goal" if goal else "Saved", shot_type=shot_type)
    return CanonicalEvent(
        event_id=event_id or f"e{n}",
        match_id="test-match",
        index=index if index is not None else n,
        period=period,
        timestamp=f"00:{minute:02d}:{second:02d}.000",
        minute=minute,
        second=second,
        type="Shot" if shot else type,
        team=team,
        player=PlayerRef(f"p{n}", player),
        shot=shot,
        card=card,
    )


def correction(
    *,
    supersedes: str,
    kind: str = "disallow",
    minute: int = 0,
    reason: str = "Offside in the build-up",
    authority: str = "VAR",
    period: int = 1,
    payload: dict | None = None,
    correction_id: str | None = None,
) -> Correction:
    return Correction(
        correction_id=correction_id or f"c-{supersedes}-{kind}-{minute}",
        match_id="test-match",
        supersedes=supersedes,
        kind=kind,  # type: ignore[arg-type]
        reason=reason,
        authority=authority,  # type: ignore[arg-type]
        period=period,
        decided_at_minute=minute,
        payload=payload or {},
        synthesised=True,
    )


@pytest.fixture
def starting_log() -> list:
    """2-1 to Argentina: goals at 20', 40' (Argentina) and 62' (France)."""
    return [
        ev(minute=0, type="Starting XI", team=HOME),
        ev(minute=0, type="Starting XI", team=AWAY),
        ev(minute=20, goal=True, xg=0.5, player="Messi", event_id="goal-1"),
        ev(minute=40, goal=True, xg=0.3, player="Di Maria", event_id="goal-2"),
        ev(minute=62, goal=True, xg=0.2, player="Mbappe", team=AWAY, period=2, event_id="goal-3"),
    ]
