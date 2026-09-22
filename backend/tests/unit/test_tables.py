"""Tie-break rules, including the three-way tie.

The scenario below is built so that the *same* results produce a *different*
order in La Liga and the Premier League. That is the whole point of the
strategy registry: one sort would silently put the wrong team in Europe.
"""

from __future__ import annotations

from onside.domain.tables import TIE_BREAKS, Result, compute

NAMES = {"A": "Alpha", "B": "Beta", "C": "Gamma", "D": "Delta"}


def test_simple_table_orders_by_points():
    results = [
        Result("A", "B", 2, 0),
        Result("A", "C", 1, 0),
        Result("B", "C", 0, 0),
    ]
    table = compute(results, competition="PL", names=NAMES)
    assert [r.team_id for r in table.rows][0] == "A"
    assert table.rows[0].points == 6
    assert table.rule_id == "PL"


def _three_way_scenario() -> list[Result]:
    """A, B, C all finish on the same points.

    Head-to-head among the three:
        A beat B 1-0, B beat C 1-0, C beat A 1-0   -> all level on h2h points
    but head-to-head goal difference is level too, so La Liga falls through to
    overall goal difference. D is the punchbag whose scorelines set the
    overall goal differences apart:
        A beat D 1-0, B beat D 4-0, C beat D 2-0
    Overall GD: B +4, C +2, A +1.
    """
    return [
        Result("A", "B", 1, 0),
        Result("B", "C", 1, 0),
        Result("C", "A", 1, 0),
        Result("A", "D", 1, 0),
        Result("B", "D", 4, 0),
        Result("C", "D", 2, 0),
    ]


def test_three_way_tie_premier_league_uses_goal_difference():
    table = compute(_three_way_scenario(), competition="PL", names=NAMES)
    top3 = [r.team_id for r in table.rows[:3]]
    assert top3 == ["B", "C", "A"], "PL separates on overall goal difference first"
    assert all(r.points == 6 for r in table.rows[:3])


def test_three_way_tie_la_liga_falls_through_to_overall_gd_when_h2h_is_level():
    table = compute(_three_way_scenario(), competition="LIGA", names=NAMES)
    top3 = [r.team_id for r in table.rows[:3]]
    # Head-to-head points and head-to-head GD are all level in the mini-table,
    # so La Liga's first two rules separate nobody and it falls to overall GD.
    assert top3 == ["B", "C", "A"]
    assert "head-to-head" in table.explanation


def test_la_liga_and_premier_league_disagree_on_the_same_results():
    """Two teams level on points; one won the head-to-head, the other has the
    better goal difference. The competitions order them differently."""
    results = [
        Result("A", "B", 1, 0),   # A won the head-to-head, so A leads it 3-0
        Result("B", "C", 6, 0),   # but B's goal difference is +5 against A's +1
    ]
    # A and B both finish on 3 points; C on 0, so the tie group is exactly {A, B}.
    pl = [r.team_id for r in compute(results, competition="PL").rows]
    liga = [r.team_id for r in compute(results, competition="LIGA").rows]
    assert pl[0] == "B", "PL puts the better goal difference first"
    assert liga[0] == "A", "La Liga puts the head-to-head winner first"
    assert pl != liga


def test_partial_split_recurses_into_the_remaining_group():
    """One rule separates one team and leaves two still level.

    The remaining pair must be re-ranked with the mini-table recomputed among
    only those two - not among the original three.
    """
    results = [
        Result("A", "B", 0, 0),
        Result("B", "C", 0, 0),
        Result("C", "A", 0, 0),
        Result("A", "D", 3, 0),
        Result("B", "D", 1, 0),
        Result("C", "D", 1, 0),
        Result("D", "A", 0, 0),
        Result("D", "B", 0, 0),
        Result("D", "C", 0, 0),
    ]
    table = compute(results, competition="PL")
    order = [r.team_id for r in table.rows]
    assert order[0] == "A", "A has the best goal difference"
    assert set(order[1:3]) == {"B", "C"}


def test_teams_that_cannot_be_separated_are_reported_not_invented():
    results = [Result("A", "B", 1, 1), Result("B", "A", 1, 1)]
    table = compute(results, competition="LIGUE_1")
    assert table.unresolved == (("A", "B"),), \
        "still level after every rule - say so rather than sorting by name"


def test_ucl_group_uses_head_to_head_away_goals():
    tb = TIE_BREAKS["UCL_GROUP"]
    assert tb.rules[0].__name__ == "head_to_head_points"
    assert tb.rules[2].__name__ == "head_to_head_away_goals"


def test_every_registered_competition_has_an_explanation():
    for key, tb in TIE_BREAKS.items():
        assert tb.explanation and tb.explanation[0].isupper(), key
        assert tb.explanation.endswith("."), key
        assert tb.rules, key
