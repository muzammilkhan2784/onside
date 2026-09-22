"""Synthesise realistic VAR corrections from a real event stream.

StatsBomb open data does **not** contain VAR overturns. Corrections are the
whole point of Onside, so the demo has to be able to show one. This module
manufactures them - deterministically, from a seed derived from the match id,
so the same match always produces the same corrections and demos and tests are
reproducible.

**Everything it produces is flagged `synthesised=True` and must be labelled as
synthesised everywhere it appears.** A viewer must never mistake one of these
for a historical fact. See SPEC.md section 19.3.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from ..domain.corrections import Correction
from ..domain.events import CanonicalEvent, sorted_canonically

DISALLOW_REASONS = (
    ("Offside in the build-up", "VAR"),
    ("Handball in the build-up", "VAR"),
    ("Foul by the attacking team in the build-up", "VAR"),
    ("Offside - armpit, on the tightest of lines", "VAR"),
)

AMEND_REASONS = (
    ("Expected-goals value revised after frame-by-frame review", "feed_correction"),
    ("Shot location corrected after review", "feed_correction"),
)

REASSIGN_REASONS = (
    ("Deflection ruled decisive - recorded as an own goal", "official_review"),
    ("Final touch reassigned after review", "official_review"),
)

#: The demo is about the decision arriving *late*. 2-4 minutes is the real
#: range for a VAR check that goes to the monitor.
MIN_DELAY, MAX_DELAY = 2, 4


def _seed_for(match_id: str) -> int:
    return int.from_bytes(match_id.encode("utf-8")[:8].ljust(8, b"\0"), "big")


def inject(
    events: Sequence[CanonicalEvent],
    *,
    match_id: str,
    disallow: int = 1,
    amend: int = 1,
    reassign: int = 0,
    target_event_id: str | None = None,
) -> list[Correction]:
    """Generate corrections against real goals in `events`.

    `target_event_id` pins the disallowed goal, which is what the demo and the
    correction test suite use so the scenario is fixed rather than merely
    reproducible.
    """
    rng = random.Random(_seed_for(match_id))
    ordered = sorted_canonically(list(events))

    # Only regulation and extra-time goals - disallowing a shootout penalty is
    # not a thing that happens.
    goals = [e for e in ordered if e.is_goal and e.period <= 4]
    shots = [e for e in ordered if e.shot is not None and e.period <= 4 and not e.is_goal]
    if not goals:
        return []

    out: list[Correction] = []
    used: set[str] = set()

    def pick(pool: list[CanonicalEvent]) -> CanonicalEvent | None:
        avail = [e for e in pool if e.event_id not in used]
        if not avail:
            return None
        chosen = rng.choice(avail)
        used.add(chosen.event_id)
        return chosen

    for i in range(disallow):
        if target_event_id and i == 0:
            target = next((e for e in goals if e.event_id == target_event_id), None)
            if target:
                used.add(target.event_id)
        else:
            target = pick(goals)
        if target is None:
            break
        reason, authority = rng.choice(DISALLOW_REASONS)
        delay = rng.randint(MIN_DELAY, MAX_DELAY)
        out.append(
            Correction(
                correction_id=f"corr-disallow-{target.event_id[:8]}",
                match_id=match_id,
                supersedes=target.event_id,
                kind="disallow",
                reason=reason,
                authority=authority,  # type: ignore[arg-type]
                period=target.period,
                decided_at_minute=target.minute + delay,
                received_at=0.0,
                synthesised=True,
            )
        )

    for _ in range(reassign):
        target = pick(goals)
        if target is None:
            break
        reason, authority = rng.choice(REASSIGN_REASONS)
        out.append(
            Correction(
                correction_id=f"corr-reassign-{target.event_id[:8]}",
                match_id=match_id,
                supersedes=target.event_id,
                kind="reassign",
                reason=reason,
                authority=authority,  # type: ignore[arg-type]
                period=target.period,
                decided_at_minute=target.minute + rng.randint(MIN_DELAY, MAX_DELAY),
                payload={"player": {"id": "own-goal", "name": "Own goal"}},
                synthesised=True,
            )
        )

    for _ in range(amend):
        target = pick(shots)
        if target is None or target.shot is None or target.shot.xg is None:
            break
        reason, authority = rng.choice(AMEND_REASONS)
        revised = round(min(0.95, max(0.01, target.shot.xg * rng.uniform(1.25, 1.8))), 3)
        out.append(
            Correction(
                correction_id=f"corr-amend-{target.event_id[:8]}",
                match_id=match_id,
                supersedes=target.event_id,
                kind="amend",
                reason=f"{reason} ({target.shot.xg:.2f} -> {revised:.2f})",
                authority=authority,  # type: ignore[arg-type]
                period=target.period,
                decided_at_minute=target.minute + rng.randint(MIN_DELAY, MAX_DELAY),
                payload={"xg": revised},
                synthesised=True,
            )
        )

    return sorted(out, key=lambda c: c.sort_key)


DISCLAIMER = (
    "StatsBomb open data does not include VAR decisions, so Onside synthesises "
    "realistic corrections from the real event stream to demonstrate the correction "
    "pipeline. Real feeds deliver these natively - see the adapter layer."
)
