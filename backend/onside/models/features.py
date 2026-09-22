"""Match state -> feature vector, and a match -> per-minute training rows.

The feature set is deliberately small and legible. Every feature is something
a person watching the game could tell you, which is what makes the model
arguable in an interview rather than a black box.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..domain.events import CanonicalEvent, EventType, sorted_canonically
from ..domain.match_state import RED_CARDS

#: Order matters - it is the column order of the model matrix, and it is
#: mirrored by the JavaScript inference used in the browser demo.
FEATURE_NAMES: tuple[str, ...] = (
    "minute",
    "minutes_remaining",
    "score_diff",
    "red_card_diff",
    "xg_diff",
    "shots_diff",
    "shots_on_target_diff",
    "possession_diff",
    "elo_diff",
    "is_neutral_venue",
)

ON_TARGET = {"Goal", "Saved", "Saved to Post", "Goal (disallowed)"}

#: Regulation only. Extra time changes what "a draw" means, so those rows are
#: excluded from training rather than quietly relabelled. See train_wp.py.
REGULATION_MINUTES = 90


@dataclass(frozen=True, slots=True)
class MinuteRow:
    match_id: str
    minute: int
    features: tuple[float, ...]
    label: int  # 0 home win, 1 draw, 2 away win


def _blank() -> dict[str, float]:
    return {"goals": 0.0, "xg": 0.0, "shots": 0.0, "sot": 0.0, "reds": 0.0, "touches": 0.0}


def minute_features(
    *,
    minute: int,
    score_diff: int,
    red_card_diff: int,
    xg_diff: float,
    shots_diff: int,
    shots_on_target_diff: int,
    possession_diff: float,
    elo_diff: float = 0.0,
    is_neutral_venue: bool = False,
) -> tuple[float, ...]:
    """Build one feature vector. Keyword-only so the column order can never
    be transposed by accident at a call site."""
    return (
        float(minute),
        float(max(REGULATION_MINUTES - minute, 0)),
        float(score_diff),
        float(red_card_diff),
        float(xg_diff),
        float(shots_diff),
        float(shots_on_target_diff),
        float(possession_diff),
        float(elo_diff),
        1.0 if is_neutral_venue else 0.0,
    )


def minute_buckets(events: Sequence[CanonicalEvent], *, home_id: str) -> dict[str, list[float]]:
    """Per-minute match state, cumulative and *exclusive* of the current minute.

    `buckets["xgH"][m]` is the home side's cumulative xG from everything that
    happened strictly before minute m - the state at the start of that minute,
    which is what a win-probability row should describe.

    This is the single source of truth for match-state accumulation: the
    training row builder and the browser demo's payload both call it, so they
    cannot drift apart. An earlier version walked the events with a cursor and
    a `minute < m` gate, which quietly broke at the period boundary - first-half
    stoppage time means a period-1 event at 47' sorts before a period-2 event at
    45', so the cursor stalled and the state at 46' was missing the start of the
    second half.
    """
    n = REGULATION_MINUTES + 1
    inc = {
        k: [0.0] * (n + 1)
        for k in (
            "xgH",
            "xgA",
            "shH",
            "shA",
            "sotH",
            "sotA",
            "goalsH",
            "goalsA",
            "redsH",
            "redsA",
            "touchH",
            "touchA",
        )
    }

    for e in events:
        if e.period > 2 or e.team is None:
            continue  # regulation only; the target is the result at 90'
        m = min(e.minute, REGULATION_MINUTES)
        side = "H" if e.team.id == home_id else "A"
        other = "A" if side == "H" else "H"
        inc[f"touch{side}"][m] += 1

        if e.shot is not None:
            inc[f"sh{side}"][m] += 1
            inc[f"xg{side}"][m] += e.shot.xg or 0.0
            if e.shot.outcome in ON_TARGET:
                inc[f"sot{side}"][m] += 1
            if e.shot.is_goal:
                inc[f"goals{side}"][m] += 1
        if e.type == EventType.OWN_GOAL_AGAINST.value:
            inc[f"goals{other}"][m] += 1
        if e.card in RED_CARDS:
            inc[f"reds{side}"][m] += 1

    out: dict[str, list[float]] = {}
    for key, series in inc.items():
        run = 0.0
        cum = [0.0] * n
        for i in range(n):
            cum[i] = run
            run += series[i]
        out[key] = cum

    # Rolling possession over the preceding ten minutes, by touch share.
    poss = [0.0] * n
    for m in range(n):
        lo = max(0, m - 10)
        h = out["touchH"][m] - out["touchH"][lo]
        a = out["touchA"][m] - out["touchA"][lo]
        poss[m] = (h - a) / (h + a) if (h + a) else 0.0
    out["possDiff"] = poss
    return out


def match_minute_rows(
    events: Sequence[CanonicalEvent],
    *,
    home_id: str,
    away_id: str,
    match_id: str,
    elo_diff: float = 0.0,
    is_neutral_venue: bool = True,
    label: int | None = None,
) -> list[MinuteRow]:
    """A feature row for every regulation minute of one match."""
    ordered = sorted_canonically(list(events))
    b = minute_buckets(ordered, home_id=home_id)

    if label is None:
        final_home = b["goalsH"][REGULATION_MINUTES] + _late_goals(ordered, home_id, True)
        final_away = b["goalsA"][REGULATION_MINUTES] + _late_goals(ordered, home_id, False)
        label = 0 if final_home > final_away else (1 if final_home == final_away else 2)

    return [
        MinuteRow(
            match_id=match_id,
            minute=m,
            features=minute_features(
                minute=m,
                score_diff=int(b["goalsH"][m] - b["goalsA"][m]),
                red_card_diff=int(b["redsH"][m] - b["redsA"][m]),
                xg_diff=b["xgH"][m] - b["xgA"][m],
                shots_diff=int(b["shH"][m] - b["shA"][m]),
                shots_on_target_diff=int(b["sotH"][m] - b["sotA"][m]),
                possession_diff=b["possDiff"][m],
                elo_diff=elo_diff,
                is_neutral_venue=is_neutral_venue,
            ),
            label=label,
        )
        for m in range(REGULATION_MINUTES + 1)
    ]


def _late_goals(events: Sequence[CanonicalEvent], home_id: str, home: bool) -> int:
    """Goals in the final minute, which the exclusive buckets stop short of."""
    total = 0
    for e in events:
        if e.period > 2 or e.team is None or e.minute < REGULATION_MINUTES:
            continue
        is_home = e.team.id == home_id
        if (
            e.shot is not None
            and e.shot.is_goal
            and is_home == home
            or e.type == EventType.OWN_GOAL_AGAINST.value
            and is_home != home
        ):
            total += 1
    return total


class Elo:
    """Causal Elo. Ratings only ever see matches that already happened.

    Built strictly in date order, so a rating used as a feature for match N
    never contains information from match N or later. Getting this wrong is
    the classic silent leak in sports models.
    """

    def __init__(self, start: float = 1500.0, k: float = 24.0) -> None:
        self.start = start
        self.k = k
        self.ratings: dict[str, float] = {}

    def get(self, team_id: str) -> float:
        return self.ratings.get(team_id, self.start)

    def diff(self, home_id: str, away_id: str) -> float:
        return self.get(home_id) - self.get(away_id)

    def update(self, home_id: str, away_id: str, home_goals: int, away_goals: int) -> None:
        rh, ra = self.get(home_id), self.get(away_id)
        expected = 1.0 / (1.0 + 10 ** ((ra - rh) / 400.0))
        actual = 1.0 if home_goals > away_goals else (0.5 if home_goals == away_goals else 0.0)
        margin = max(abs(home_goals - away_goals), 1) ** 0.5
        delta = self.k * margin * (actual - expected)
        self.ratings[home_id] = rh + delta
        self.ratings[away_id] = ra - delta
