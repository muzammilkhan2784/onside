"""Response models. These are what /docs publishes as the API contract.

The large per-match payloads (timeline, stats, shots) are typed loosely with
`dict` fields on purpose: they are produced by one builder and consumed by one
client, and the example in each route's docstring documents them. The listing
and control types - the ones third parties actually integrate against - are
typed field by field.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Ref(BaseModel):
    id: str
    name: str


class MatchCard(BaseModel):
    id: str
    competition: dict[str, Any]
    season: dict[str, Any]
    date: str
    kickoff: str = ""
    stage: str = ""
    matchWeek: int | None = None
    home: Ref
    away: Ref
    score: list[int]
    shootout: list[int] | None = None
    status: str = "finished"
    xg: list[float | None] = Field(default_factory=list)
    headline: str = ""
    standfirst: str = ""
    tags: list[str] = Field(default_factory=list)
    biggestSwing: float = 0
    hasFreezeFrames: bool = False
    live: bool = False


class Page(BaseModel, Generic[T]):
    items: list[T]
    next: str | None = Field(
        None, description="Pass as `cursor` to get the next page. Null on the last page."
    )


class Season(BaseModel):
    id: str
    name: str
    matches: int
    from_: str = Field(alias="from")
    to: str

    model_config = {"populate_by_name": True}


class Competition(BaseModel):
    id: str
    name: str
    country: str
    gender: str
    international: bool
    youth: bool = False
    matches: int
    seasons: list[Season]


class TableRow(BaseModel):
    position: int
    teamId: str
    team: str
    played: int
    won: int
    drawn: int
    lost: int
    goalsFor: int
    goalsAgainst: int
    goalDifference: int
    points: int


class Table(BaseModel):
    group: str
    ruleId: str
    explanation: str = Field(
        description="How this competition separates teams level on points, in plain English."
    )
    note: str = ""
    unresolved: list[list[str]] = Field(default_factory=list)
    rows: list[TableRow]


class Tables(BaseModel):
    competitionId: str
    seasonId: str
    tables: list[Table]
    note: str = Field("", description="Why there is no table, or how groups were recovered.")


class Correction(BaseModel):
    id: str
    supersedes: str
    kind: str = Field(description="disallow | reassign | amend | reinstate")
    reason: str
    authority: str
    period: int
    decidedAt: int
    synthesised: bool = Field(
        description="True when Onside generated this correction for a replay."
    )
    headline: str = ""


class WinProbabilityPoint(BaseModel):
    minute: int
    p_home: float
    p_draw: float
    p_away: float


class WinProbability(BaseModel):
    matchId: str
    range: str
    series: list[WinProbabilityPoint]


class ScoreAt(BaseModel):
    matchId: str
    period: int
    minute: int
    score: list[int]
    goalsSoFar: list[dict[str, Any]]
    note: str = ""


class LeaderboardRow(BaseModel):
    playerId: str
    player: str
    team: str | None
    matches: int
    value: float


class Leaderboard(BaseModel):
    metric: str
    description: str
    competitionId: int | None
    seasonId: int | None
    rows: list[LeaderboardRow]
    queryMs: float


class SearchResult(BaseModel):
    kind: str
    id: str
    name: str
    subtitle: str = ""


class ReplayRequest(BaseModel):
    match_id: int = Field(3869685, description="A StatsBomb match id from the archive.")
    speed: float = Field(30, ge=1, le=600, description="Match-seconds per real second.")
    inject_var: bool = Field(
        True, description="Synthesise a VAR correction to demonstrate the pipeline."
    )


class ReplayCommand(BaseModel):
    match_id: str = Field(description="The live id, e.g. `live-3869685`.")
    speed: float | None = Field(None, ge=1, le=600)


class ReplayStatus(BaseModel):
    matchId: str
    of: str = ""
    title: str = ""
    status: str
    speed: float = 0
    sent: int = 0
    total: int = 0
    minute: int = 0


class ErrorEnvelope(BaseModel):
    error: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
