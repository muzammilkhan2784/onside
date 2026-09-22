"""The feed adapter protocol.

"Every soccer game in the world" is not achievable on free data, and
pretending otherwise would undermine the whole project. So Onside is
feed-agnostic instead: adapters normalise into the canonical event model, and
each one *declares what it can actually provide*.

The UI reads `capabilities()` and degrades honestly - "this competition's feed
gives scores and lineups but not shot-level data" - rather than rendering an
empty shot map and letting the viewer conclude the site is broken.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..domain.corrections import Correction
from ..domain.events import CanonicalEvent


@dataclass(frozen=True, slots=True)
class FeedCapabilities:
    """What a feed genuinely provides. Never aspirational."""

    name: str
    has_events: bool = False
    has_xg: bool = False
    has_freeze_frames: bool = False
    has_lineups: bool = False
    has_corrections: bool = False
    is_live: bool = False
    update_seconds: int | None = None
    licence: str = ""

    def explain_missing(self, what: str) -> str:
        """Plain-English copy for a capability this feed does not have.

        Every empty state in the product is written, not left blank - see
        SPEC.md section 1.
        """
        human = {
            "has_events": "shot-by-shot event data",
            "has_xg": "expected-goals values",
            "has_freeze_frames": "player positions at the moment of a shot",
            "has_lineups": "confirmed lineups",
            "has_corrections": "VAR and post-match corrections",
        }.get(what, what)
        return (
            f"This competition is covered by the {self.name} feed, which does not "
            f"provide {human}, so there is nothing to show here. It is not an error."
        )


@dataclass(frozen=True, slots=True)
class CompetitionRef:
    id: str
    name: str
    season_id: str = ""
    season_name: str = ""


@dataclass(frozen=True, slots=True)
class MatchRef:
    id: str
    home: str
    away: str
    kickoff_utc: str = ""
    competition_id: str = ""
    status: str = "scheduled"


@runtime_checkable
class FeedAdapter(Protocol):
    """Every feed implements this, and the contract suite runs against all of
    them with the same assertions."""

    name: str

    def capabilities(self) -> FeedCapabilities: ...

    def list_competitions(self) -> Sequence[CompetitionRef]: ...

    def list_matches(self, competition_id: str, season_id: str) -> Sequence[MatchRef]: ...

    def fetch_events(self, match_id: str) -> Sequence[CanonicalEvent]: ...

    def normalise(self, raw: dict[str, Any], match_id: str) -> CanonicalEvent | Correction: ...


class StreamingFeedAdapter(FeedAdapter, Protocol):
    """A live feed additionally streams. Historical feeds do not pretend to."""

    def stream_events(self, match_id: str) -> AsyncIterator[CanonicalEvent | Correction]: ...
