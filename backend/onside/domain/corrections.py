"""Corrections as first-class events.

The single rule this project is built around:

    **The event log is append-only. Nothing is ever updated or deleted.**

VAR disallows a goal, a scorer gets reassigned, xG gets revised. Every other
site mutates a row and the score silently changes. Onside appends a
`Correction` that *supersedes* an earlier event, so the timeline can still show

    Goal 62'  ->  disallowed by VAR at 64', offside in the build-up

and the projection can still answer "was this ever 2-1?".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CorrectionKind = Literal["disallow", "reassign", "amend", "reinstate"]
Authority = Literal["VAR", "referee", "feed_correction", "official_review"]

#: What each kind does to the projection. Kept beside the type so the UI and
#: the README can read the same table the projector obeys.
#: How each authority is named to a person. Never show a bare enum.
AUTHORITY_LABEL: dict[str, str] = {
    "VAR": "VAR",
    "referee": "the referee",
    "feed_correction": "the data provider",
    "official_review": "an official review",
}

KIND_EFFECT: dict[str, str] = {
    "disallow": "stops counting, stays visible in the timeline struck through",
    "reassign": "attribution changes, the score does not",
    "amend": "one field changes (xG revised, minute corrected)",
    "reinstate": "a previous disallow is itself reversed",
}


@dataclass(frozen=True, slots=True)
class Correction:
    """An append-only record that changes how an earlier event is projected."""

    correction_id: str
    match_id: str
    supersedes: str  # the event_id being corrected
    kind: CorrectionKind
    reason: str  # "Offside in the build-up"
    authority: Authority
    period: int
    decided_at_minute: int  # when the decision was made, not when the event was
    payload: dict[str, Any] = field(default_factory=dict)
    received_at: float = 0.0

    #: True when Onside generated this correction for the demo rather than
    #: receiving it from a feed. Surfaced everywhere it appears - see
    #: SPEC.md section 19.3. Honesty here is part of what the project argues for.
    synthesised: bool = False

    @property
    def sort_key(self) -> tuple[int, int, int, str]:
        """Corrections apply in the order the decisions were made."""
        return (self.period, self.decided_at_minute, 1, self.correction_id)

    @property
    def headline(self) -> str:
        """One plain-English line. Never show a bare enum to a human."""
        verb = {
            "disallow": "Goal disallowed",
            "reassign": "Goal reassigned",
            "amend": "Detail corrected",
            "reinstate": "Goal reinstated",
        }[self.kind]
        return f"{verb} by {AUTHORITY_LABEL.get(self.authority, self.authority)} - {self.reason}"


@dataclass(frozen=True, slots=True)
class Supersession:
    """The resolved verdict on one event after every correction is applied."""

    event_id: str
    disallowed: bool = False
    reason: str = ""
    authority: str = ""
    decided_at_minute: int | None = None
    synthesised: bool = False
    amendments: dict[str, Any] = field(default_factory=dict)
    history: tuple[Correction, ...] = ()

    @property
    def was_corrected(self) -> bool:
        return bool(self.history)


def resolve(corrections: list[Correction] | tuple[Correction, ...]) -> dict[str, Supersession]:
    """Fold every correction into one verdict per superseded event.

    Corrections are applied in decision order, so a `reinstate` that follows a
    `disallow` wins, and applying the same correction twice is a no-op
    (correction ids are unique and deduplicated here).
    """
    seen: set[str] = set()
    ordered: list[Correction] = []
    for c in sorted(corrections, key=lambda c: c.sort_key):
        if c.correction_id in seen:
            continue  # idempotent: the same correction twice changes nothing
        seen.add(c.correction_id)
        ordered.append(c)

    out: dict[str, Supersession] = {}
    for c in ordered:
        prev = out.get(c.supersedes, Supersession(event_id=c.supersedes))
        amendments = dict(prev.amendments)
        disallowed = prev.disallowed

        if c.kind == "disallow":
            disallowed = True
        elif c.kind == "reinstate":
            disallowed = False
        elif c.kind in ("reassign", "amend"):
            amendments.update(c.payload)

        out[c.supersedes] = Supersession(
            event_id=c.supersedes,
            disallowed=disallowed,
            reason=c.reason,
            authority=c.authority,
            decided_at_minute=c.decided_at_minute,
            synthesised=c.synthesised or prev.synthesised,
            amendments=amendments,
            history=prev.history + (c,),
        )
    return out
