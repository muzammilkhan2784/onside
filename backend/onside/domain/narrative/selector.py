"""Pick the moments that actually decided the match.

The report is not a stat dump and not wire copy: it is the match ranked by how
much each moment moved the win probability, which is a number the system
already computed for its own purposes. The narrative falls out of the model.

Pure module - it takes a state, a log and a probability series, and returns
moments. No I/O, no templating, no prose.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from ..events import CanonicalEvent, EventType, sorted_canonically
from ..match_state import MatchState

MomentKind = Literal[
    "goal", "disallowed_goal", "red_card", "penalty_miss", "big_chance", "correction", "full_time"
]

#: A report of six to eight moments reads; twelve does not.
MIN_MOMENTS, MAX_MOMENTS = 6, 8

#: Two events 90 seconds apart are usually the same passage of play. Keep the
#: bigger one so the report does not say the same thing twice.
DUPLICATE_WINDOW_SECONDS = 90

#: Below this, a shot is not worth a sentence unless something else marks it.
BIG_CHANCE_XG = 0.30


@dataclass(frozen=True, slots=True)
class Moment:
    kind: MomentKind
    period: int
    minute: int
    second: int
    event_id: str
    team_id: str
    team_name: str
    player: str
    swing: float  # |delta win probability| for the eventual winner
    wp_before: tuple[float, float, float]
    wp_after: tuple[float, float, float]
    score_after: tuple[int, int]
    xg: float | None = None
    shot_type: str = ""
    detail: str = ""
    synthesised: bool = False
    #: When a correction took this event off the board, in match minutes.
    ruled_out_at: int | None = None
    #: Always-include moments are in the report regardless of swing.
    mandatory: bool = False

    @property
    def abs_minute(self) -> int:
        """Minute on a single axis across normal and extra time."""
        return self.minute


def _probs_at(series: Sequence[Mapping[str, float]], minute: int) -> tuple[float, float, float]:
    """Win probability at the *start* of a minute, clamped to the series ends.

    The series describes the state before anything in that minute happened, so
    an event at minute m is bracketed by (m, m+1) - not (m-1, m). Getting this
    wrong attributes each goal's swing to the minute before it, which in the
    2022 final credited Mbappe's 80th-minute equaliser with the effect of his
    own penalty a minute earlier.
    """
    if not series:
        return (1 / 3, 1 / 3, 1 / 3)
    best = series[0]
    for pt in series:
        if pt["minute"] <= minute:
            best = pt
        else:
            break
    return (best["p_home"], best["p_draw"], best["p_away"])


def _winner_class(state: MatchState) -> int:
    h, a = state.score
    if state.shootout:
        sh, sa = state.shootout_score
        if sh != sa:
            return 0 if sh > sa else 2
    return 0 if h > a else (1 if h == a else 2)


def select(
    state: MatchState,
    events: Sequence[CanonicalEvent],
    wp_series: Sequence[Mapping[str, float]],
    *,
    max_moments: int = MAX_MOMENTS,
) -> list[Moment]:
    """Rank, filter and order the moments that make up the report.

    1. Compute the swing for every candidate.
    2. Always include goals, reds, penalties, corrections and the final whistle.
    3. Add the highest-swing remaining moments up to the cap.
    4. Suppress near-duplicates, keeping the larger.
    5. Order chronologically.
    """
    ordered = sorted_canonically(list(events))
    winner = _winner_class(state)
    corrections_by_event = {c.supersedes: c for c in state.corrections}
    candidates: list[Moment] = []

    running = [0, 0]
    home_id = state.home.id if state.home else ""

    for e in ordered:
        if e.period == 5:  # the shootout gets its own closing line
            continue
        before = _probs_at(wp_series, e.minute)
        after = _probs_at(wp_series, e.minute + 1)
        swing = abs(after[winner] - before[winner])
        corr = corrections_by_event.get(e.event_id)
        team_name = e.team.name if e.team else ""
        team_id = e.team.id if e.team else ""
        player = e.player.name if e.player else ""

        if e.is_goal or e.type == EventType.OWN_GOAL_AGAINST.value:
            disallowed = bool(corr and corr.kind == "disallow")
            if not disallowed:
                if e.type == EventType.OWN_GOAL_AGAINST.value:
                    running[1 if team_id == home_id else 0] += 1
                else:
                    running[0 if team_id == home_id else 1] += 1
            candidates.append(
                Moment(
                    kind="disallowed_goal" if disallowed else "goal",
                    period=e.period,
                    minute=e.minute,
                    second=e.second,
                    event_id=e.event_id,
                    team_id=team_id,
                    team_name=team_name,
                    player=player,
                    swing=swing,
                    wp_before=before,
                    wp_after=after,
                    score_after=(running[0], running[1]),
                    xg=e.shot.xg if e.shot else None,
                    shot_type=e.shot.shot_type if e.shot else "Own Goal",
                    detail=corr.reason if corr else "",
                    synthesised=bool(corr and corr.synthesised),
                    ruled_out_at=corr.decided_at_minute if disallowed and corr else None,
                    mandatory=True,
                )
            )
            continue

        if e.card in ("Red Card", "Second Yellow"):
            candidates.append(
                Moment(
                    kind="red_card",
                    period=e.period,
                    minute=e.minute,
                    second=e.second,
                    event_id=e.event_id,
                    team_id=team_id,
                    team_name=team_name,
                    player=player,
                    swing=swing,
                    wp_before=before,
                    wp_after=after,
                    score_after=(running[0], running[1]),
                    detail=e.card or "",
                    mandatory=True,
                )
            )
            continue

        if e.shot is not None and e.shot.shot_type == "Penalty" and not e.shot.is_goal:
            candidates.append(
                Moment(
                    kind="penalty_miss",
                    period=e.period,
                    minute=e.minute,
                    second=e.second,
                    event_id=e.event_id,
                    team_id=team_id,
                    team_name=team_name,
                    player=player,
                    swing=swing,
                    wp_before=before,
                    wp_after=after,
                    score_after=(running[0], running[1]),
                    xg=e.shot.xg,
                    shot_type="Penalty",
                    detail=e.shot.outcome,
                    mandatory=True,
                )
            )
            continue

        if e.shot is not None and (e.shot.xg or 0) >= BIG_CHANCE_XG:
            candidates.append(
                Moment(
                    kind="big_chance",
                    period=e.period,
                    minute=e.minute,
                    second=e.second,
                    event_id=e.event_id,
                    team_id=team_id,
                    team_name=team_name,
                    player=player,
                    swing=swing,
                    wp_before=before,
                    wp_after=after,
                    score_after=(running[0], running[1]),
                    xg=e.shot.xg,
                    shot_type=e.shot.shot_type,
                    detail=e.shot.outcome,
                )
            )

    mandatory = [m for m in candidates if m.mandatory]
    optional = sorted(
        (m for m in candidates if not m.mandatory), key=lambda m: m.swing, reverse=True
    )

    chosen = list(mandatory)
    for m in optional:
        if len(chosen) >= max_moments:
            break
        chosen.append(m)

    chosen = _suppress_duplicates(chosen)
    chosen.sort(key=lambda m: (m.period, m.minute, m.second))
    return chosen


def _suppress_duplicates(moments: list[Moment]) -> list[Moment]:
    """Drop the smaller of any two moments inside the duplicate window.

    A goal is never suppressed by a chance: the mandatory moments are the
    spine of the report.
    """
    kept: list[Moment] = []
    for m in sorted(moments, key=lambda m: m.swing, reverse=True):
        clash = False
        for k in kept:
            same_period = k.period == m.period
            gap = abs((k.minute * 60 + k.second) - (m.minute * 60 + m.second))
            if same_period and gap <= DUPLICATE_WINDOW_SECONDS:
                if m.mandatory and not k.mandatory:
                    continue  # the mandatory one replaces it below
                clash = True
                break
        if clash:
            continue
        kept = [
            k
            for k in kept
            if not (
                m.mandatory
                and not k.mandatory
                and k.period == m.period
                and abs((k.minute * 60 + k.second) - (m.minute * 60 + m.second))
                <= DUPLICATE_WINDOW_SECONDS
            )
        ]
        kept.append(m)
    return kept


def biggest_swing(moments: Sequence[Moment]) -> Moment | None:
    return max(moments, key=lambda m: m.swing) if moments else None
