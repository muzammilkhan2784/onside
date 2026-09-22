"""Events -> a wall-clock schedule the driver can emit at any speed.

StatsBomb minutes run continuously across a match (the second half starts at
45:00), but periods overlap on the clock: first-half stoppage time at 47:10
happens *before* the second half's 45:00. So the schedule is built per period:
each period starts where the previous one ended, plus a short break, and events
are placed by their offset from their own period's start.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ..domain.corrections import Correction
from ..domain.events import CanonicalEvent, sorted_canonically

PERIOD_CLOCK_START = {1: 0, 2: 45 * 60, 3: 90 * 60, 4: 105 * 60, 5: 120 * 60}
#: Match-seconds between periods. Real half-time is 15 minutes; nobody wants
#: to watch that at any speed.
BREAK_SECONDS = 60
#: A VAR check lands this many match-seconds into its decision minute.
CORRECTION_OFFSET = 30


@dataclass(frozen=True, slots=True)
class Scheduled:
    at: float  # match-seconds from kick-off, monotonic
    kind: Literal["event", "correction"]
    record: CanonicalEvent | Correction


def build(
    events: Sequence[CanonicalEvent], corrections: Sequence[Correction] = ()
) -> list[Scheduled]:
    ordered = sorted_canonically(list(events))
    by_period: dict[int, list[CanonicalEvent]] = {}
    for e in ordered:
        by_period.setdefault(e.period, []).append(e)

    starts: dict[int, float] = {}
    cursor = 0.0
    for period in sorted(by_period):
        starts[period] = cursor
        clock0 = PERIOD_CLOCK_START.get(period, 0)
        last = max(e.minute * 60 + e.second for e in by_period[period])
        cursor += max(last - clock0, 0) + BREAK_SECONDS

    def offset(period: int, minute: int, second: int) -> float:
        return starts.get(period, cursor) + max(
            minute * 60 + second - PERIOD_CLOCK_START.get(period, 0), 0
        )

    out = [Scheduled(offset(e.period, e.minute, e.second), "event", e) for e in ordered]
    out += [
        Scheduled(offset(c.period, c.decided_at_minute, CORRECTION_OFFSET), "correction", c)
        for c in corrections
    ]
    # Stable: events keep their canonical order within the same second.
    out.sort(key=lambda s: s.at)
    return out


def duration(schedule: Sequence[Scheduled]) -> float:
    return schedule[-1].at if schedule else 0.0
