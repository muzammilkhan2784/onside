"""The canonical event taxonomy.

Onside's internal event model follows StatsBomb's, because it is the most
complete public taxonomy. Every other feed normalises *into* this shape.

This module is pure: no I/O, no framework, stdlib only. Everything downstream
(the fold, corrections, narrative, features) depends on it, so it stays cheap
to import and trivial to test.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Literal

# The pitch is 120 x 80, origin top-left, the acting team attacking left to right.
PITCH_LENGTH = 120.0
PITCH_WIDTH = 80.0


class EventType(str, Enum):
    """The subset of the StatsBomb taxonomy Onside projects over.

    Events outside this set are still stored verbatim in the log; they simply
    do not move the projection. Keeping the enum narrow keeps the fold honest.
    """

    PASS = "Pass"
    SHOT = "Shot"
    CARRY = "Carry"
    DRIBBLE = "Dribble"
    DUEL = "Duel"
    PRESSURE = "Pressure"
    INTERCEPTION = "Interception"
    CLEARANCE = "Clearance"
    BLOCK = "Block"
    GOAL_KEEPER = "Goal Keeper"
    BALL_RECEIPT = "Ball Receipt*"
    BALL_RECOVERY = "Ball Recovery"
    MISCONTROL = "Miscontrol"
    DISPOSSESSED = "Dispossessed"
    FOUL_COMMITTED = "Foul Committed"
    FOUL_WON = "Foul Won"
    BAD_BEHAVIOUR = "Bad Behaviour"
    OFFSIDE = "Offside"
    OWN_GOAL_AGAINST = "Own Goal Against"
    OWN_GOAL_FOR = "Own Goal For"
    SUBSTITUTION = "Substitution"
    STARTING_XI = "Starting XI"
    TACTICAL_SHIFT = "Tactical Shift"
    HALF_START = "Half Start"
    HALF_END = "Half End"
    INJURY_STOPPAGE = "Injury Stoppage"
    PLAYER_ON = "Player On"
    PLAYER_OFF = "Player Off"
    ERROR = "Error"
    SHIELD = "Shield"
    FIFTY_FIFTY = "50/50"
    REFEREE_BALL_DROP = "Referee Ball-Drop"
    DRIBBLED_PAST = "Dribbled Past"


#: Periods 1-2 are normal time, 3-4 extra time, 5 the shootout.
Period = int

Card = Literal["Yellow Card", "Second Yellow", "Red Card"]

#: A shot that beat the keeper. Everything else did not.
GOAL = "Goal"


@dataclass(frozen=True, slots=True)
class TeamRef:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class PlayerRef:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class FreezeFrameActor:
    """One visible player at the instant of a shot, from StatsBomb 360."""

    x: float
    y: float
    teammate: bool
    keeper: bool
    name: str = ""


@dataclass(frozen=True, slots=True)
class ShotDetail:
    xg: float | None = None
    outcome: str = ""
    shot_type: str = ""  # Open Play / Penalty / Free Kick / Corner / Kick Off
    body_part: str = ""
    technique: str = ""
    end_location: tuple[float, ...] = ()
    freeze_frame: tuple[FreezeFrameActor, ...] = ()
    key_pass_id: str | None = None
    first_time: bool = False
    one_on_one: bool = False

    @property
    def is_goal(self) -> bool:
        return self.outcome == GOAL


@dataclass(frozen=True, slots=True)
class PassDetail:
    recipient: PlayerRef | None = None
    length: float | None = None
    angle: float | None = None
    height: str = ""
    end_location: tuple[float, ...] = ()
    body_part: str = ""
    pass_type: str = ""
    outcome: str = ""  # empty means complete - StatsBomb only records failures
    technique: str = ""
    cross: bool = False
    cut_back: bool = False
    switch: bool = False
    through_ball: bool = False
    shot_assist: bool = False
    goal_assist: bool = False

    @property
    def complete(self) -> bool:
        return self.outcome == ""


@dataclass(frozen=True, slots=True)
class CanonicalEvent:
    """One thing that happened, as Onside stores it forever.

    `event_id` is stable across corrections: a correction never rewrites the
    event, it supersedes it (see `corrections.py`).
    """

    event_id: str
    match_id: str
    index: int
    period: Period
    timestamp: str  # HH:MM:SS.mmm within the period
    minute: int
    second: int
    type: str
    team: TeamRef | None = None
    player: PlayerRef | None = None
    position: str = ""
    possession: int = 0
    possession_team: TeamRef | None = None
    play_pattern: str = ""
    location: tuple[float, float] | None = None
    duration: float | None = None
    under_pressure: bool = False
    counterpress: bool = False
    out: bool = False
    related_events: tuple[str, ...] = ()

    shot: ShotDetail | None = None
    pass_: PassDetail | None = None
    card: str | None = None
    duel_type: str = ""  # Tackle / Aerial Lost - PPDA counts tackles, not lost headers
    substitution_replacement: PlayerRef | None = None
    tactics: dict[str, Any] | None = None

    # Provenance. Two sites report different xG and neither says which model;
    # Onside always says. See SPEC.md section 12.2.
    source_feed: str = ""
    source_event_id: str = ""

    extra: dict[str, Any] = field(default_factory=dict, compare=False)

    # ---- ordering ------------------------------------------------------
    @property
    def sort_key(self) -> tuple[int, int, int, int]:
        """Canonical match order, independent of the order events arrived in."""
        return (self.period, self.minute, self.second, self.index)

    @property
    def is_goal(self) -> bool:
        return self.shot is not None and self.shot.is_goal

    @property
    def is_own_goal(self) -> bool:
        return self.type == EventType.OWN_GOAL_AGAINST.value

    @property
    def is_penalty_shot(self) -> bool:
        return self.shot is not None and self.shot.shot_type == "Penalty"

    @property
    def is_shootout(self) -> bool:
        return self.period == 5

    def with_index(self, index: int) -> CanonicalEvent:
        return replace(self, index=index)


def sorted_canonically(
    events: list[CanonicalEvent] | tuple[CanonicalEvent, ...],
) -> list[CanonicalEvent]:
    """Order events the way the match actually happened.

    Feeds deliver out of order. The log stores arrival order; the projector
    always sorts by (period, minute, second, index) first. This function is the
    single place that ordering is defined, so the property test in
    tests/correction has exactly one thing to pin down.
    """
    return sorted(events, key=lambda e: e.sort_key)
