"""League tables, and the tie-break rules that differ by competition.

La Liga separates level teams on head-to-head record *before* goal difference.
The Premier League does the opposite. Getting this wrong puts the wrong team
in the Champions League places, so it is encoded as an explicit strategy per
competition rather than one hard-coded sort, and the table records which rule
it applied so the UI can say so.

Head-to-head is recursive: with three teams level you build a mini-table among
only those three, which can itself produce ties.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

WIN, DRAW, LOSS = 3, 1, 0


@dataclass(frozen=True, slots=True)
class Result:
    """One finished match, reduced to what a table needs."""

    home_id: str
    away_id: str
    home_goals: int
    away_goals: int

    def points_for(self, team_id: str) -> int:
        gf, ga = self.goals_for(team_id), self.goals_against(team_id)
        return WIN if gf > ga else (DRAW if gf == ga else LOSS)

    def involves(self, team_id: str) -> bool:
        return team_id in (self.home_id, self.away_id)

    def goals_for(self, team_id: str) -> int:
        return self.home_goals if team_id == self.home_id else self.away_goals

    def goals_against(self, team_id: str) -> int:
        return self.away_goals if team_id == self.home_id else self.home_goals

    def away_goals_for(self, team_id: str) -> int:
        """Goals scored away from home, for competitions that still use it."""
        return self.away_goals if team_id == self.away_id else 0


@dataclass(frozen=True, slots=True)
class Row:
    team_id: str
    team_name: str = ""
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0

    @property
    def points(self) -> int:
        return self.won * WIN + self.drawn * DRAW

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against


def build_rows(results: Sequence[Result], names: dict[str, str] | None = None) -> dict[str, Row]:
    names = names or {}
    acc: dict[str, dict[str, int]] = {}
    for r in results:
        for tid in (r.home_id, r.away_id):
            a = acc.setdefault(
                tid, {"played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0}
            )
            gf, ga = r.goals_for(tid), r.goals_against(tid)
            a["played"] += 1
            a["gf"] += gf
            a["ga"] += ga
            if gf > ga:
                a["won"] += 1
            elif gf == ga:
                a["drawn"] += 1
            else:
                a["lost"] += 1
    return {
        tid: Row(
            team_id=tid,
            team_name=names.get(tid, tid),
            played=a["played"],
            won=a["won"],
            drawn=a["drawn"],
            lost=a["lost"],
            goals_for=a["gf"],
            goals_against=a["ga"],
        )
        for tid, a in acc.items()
    }


# ---------------------------------------------------------------------------
# tie-break rules
# ---------------------------------------------------------------------------

#: A rule scores a team *within the group of tied teams*. Higher is better.
TieBreakRule = Callable[[str, Sequence[str], Sequence[Result], dict[str, Row]], float]


def goal_difference(
    team: str, group: Sequence[str], results: Sequence[Result], rows: dict[str, Row]
) -> float:
    return float(rows[team].goal_difference)


def goals_for(
    team: str, group: Sequence[str], results: Sequence[Result], rows: dict[str, Row]
) -> float:
    return float(rows[team].goals_for)


def _mini(group: Sequence[str], results: Sequence[Result]) -> list[Result]:
    """Only the matches played between the tied teams."""
    s = set(group)
    return [r for r in results if r.home_id in s and r.away_id in s]


def head_to_head_points(
    team: str, group: Sequence[str], results: Sequence[Result], rows: dict[str, Row]
) -> float:
    return float(sum(r.points_for(team) for r in _mini(group, results) if r.involves(team)))


def head_to_head_gd(
    team: str, group: Sequence[str], results: Sequence[Result], rows: dict[str, Row]
) -> float:
    mini = [r for r in _mini(group, results) if r.involves(team)]
    return float(sum(r.goals_for(team) - r.goals_against(team) for r in mini))


def head_to_head_away_goals(
    team: str, group: Sequence[str], results: Sequence[Result], rows: dict[str, Row]
) -> float:
    return float(sum(r.away_goals_for(team) for r in _mini(group, results)))


def head_to_head_goals_for(
    team: str, group: Sequence[str], results: Sequence[Result], rows: dict[str, Row]
) -> float:
    return float(sum(r.goals_for(team) for r in _mini(group, results) if r.involves(team)))


def away_goals(
    team: str, group: Sequence[str], results: Sequence[Result], rows: dict[str, Row]
) -> float:
    return float(sum(r.away_goals_for(team) for r in results if r.involves(team)))


@dataclass(frozen=True, slots=True)
class TieBreak:
    rule_id: str
    explanation: str
    rules: tuple[TieBreakRule, ...]


#: Registry. Adding a competition means adding a row here, not editing a sort.
TIE_BREAKS: dict[str, TieBreak] = {
    "PL": TieBreak(
        "PL",
        "The Premier League separates level teams on goal difference, then goals scored, then head-to-head record.",
        (goal_difference, goals_for, head_to_head_points),
    ),
    "LIGA": TieBreak(
        "LIGA",
        "La Liga separates level teams on head-to-head record first, before overall goal difference.",
        (head_to_head_points, head_to_head_gd, goal_difference, goals_for),
    ),
    "SERIE_A": TieBreak(
        "SERIE_A",
        "Serie A separates level teams on head-to-head record, then goal difference, then goals scored.",
        (head_to_head_points, goal_difference, goals_for),
    ),
    "BUNDESLIGA": TieBreak(
        "BUNDESLIGA",
        "The Bundesliga separates level teams on goal difference, then goals scored, then head-to-head record.",
        (goal_difference, goals_for, head_to_head_points),
    ),
    "LIGUE_1": TieBreak(
        "LIGUE_1",
        "Ligue 1 separates level teams on goal difference, then goals scored.",
        (goal_difference, goals_for),
    ),
    "UCL_GROUP": TieBreak(
        "UCL_GROUP",
        "Champions League groups separate level teams on head-to-head points, head-to-head goal difference and head-to-head away goals before overall figures.",
        (
            head_to_head_points,
            head_to_head_gd,
            head_to_head_away_goals,
            goal_difference,
            goals_for,
            away_goals,
        ),
    ),
    "FIFA_GROUP": TieBreak(
        "FIFA_GROUP",
        "World Cup groups separate level teams on goal difference and goals scored across all "
        "group games first, and only then on head-to-head results.",
        (goal_difference, goals_for, head_to_head_points, head_to_head_gd, head_to_head_goals_for),
    ),
    "UEFA_EURO_GROUP": TieBreak(
        "UEFA_EURO_GROUP",
        "European Championship groups separate level teams on their head-to-head results first, "
        "before overall goal difference.",
        (head_to_head_points, head_to_head_gd, head_to_head_goals_for, goal_difference, goals_for),
    ),
}

DEFAULT_TIE_BREAK = "PL"


@dataclass(frozen=True, slots=True)
class Table:
    rows: tuple[Row, ...]
    rule_id: str
    explanation: str
    #: Teams still level after every rule, by position - surfaced rather than
    #: silently broken by team name.
    unresolved: tuple[tuple[str, ...], ...] = ()


def compute(
    results: Sequence[Result],
    *,
    competition: str = DEFAULT_TIE_BREAK,
    names: dict[str, str] | None = None,
) -> Table:
    """Build the table and apply the competition's tie-break rules."""
    tb = TIE_BREAKS.get(competition, TIE_BREAKS[DEFAULT_TIE_BREAK])
    rows = build_rows(results, names)

    # Group by points first - tie-breaks only ever apply within a points group.
    by_points: dict[int, list[str]] = {}
    for tid, row in rows.items():
        by_points.setdefault(row.points, []).append(tid)

    ordered: list[Row] = []
    unresolved: list[tuple[str, ...]] = []

    for pts in sorted(by_points, reverse=True):
        group = by_points[pts]
        if len(group) == 1:
            ordered.append(rows[group[0]])
            continue
        ranked, stuck = _break_tie(group, results, rows, tb.rules)
        ordered.extend(rows[t] for t in ranked)
        unresolved.extend(stuck)

    return Table(tuple(ordered), tb.rule_id, tb.explanation, tuple(unresolved))


def _break_tie(
    group: Sequence[str],
    results: Sequence[Result],
    rows: dict[str, Row],
    rules: Sequence[TieBreakRule],
) -> tuple[list[str], list[tuple[str, ...]]]:
    """Rank a group of level teams, recursing when a rule only partly splits it.

    Recursion matters: with three teams level, a rule may separate one of them
    and leave two still tied. The remaining two must then be re-ranked with the
    mini-table recomputed among only those two, not among the original three.
    """
    if len(group) <= 1:
        return list(group), []

    for i, rule in enumerate(rules):
        scored: dict[float, list[str]] = {}
        for team in group:
            scored.setdefault(rule(team, group, results, rows), []).append(team)
        if len(scored) == 1:
            continue  # this rule separates nobody; try the next one

        out: list[str] = []
        stuck: list[tuple[str, ...]] = []
        for score in sorted(scored, reverse=True):
            sub = scored[score]
            if len(sub) == 1:
                out.append(sub[0])
            else:
                # Re-rank the smaller group from the top of the rule list:
                # its mini-table is now different.
                sub_ranked, sub_stuck = _break_tie(sub, results, rows, rules[i + 1 :])
                out.extend(sub_ranked)
                stuck.extend(sub_stuck)
        return out, stuck

    # Every rule exhausted and still level. Say so rather than inventing an order.
    return sorted(group), [tuple(sorted(group))]
