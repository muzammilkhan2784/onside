"""The signature suite.

If these pass, Onside's central claim holds: the match state is a pure fold
over an append-only log, corrections are ordinary records in that log, and the
projection depends only on the set of records - never on the order they
arrived, never on how many times they arrived.
"""

from __future__ import annotations

import random

import pytest

from onside.domain.match_state import project, project_until
from tests.conftest import AWAY, HOME, correction, ev


def test_disallowed_goal_removes_from_score_but_stays_in_timeline(starting_log):
    before = project(starting_log)
    assert before.score == (2, 1)

    after = project(starting_log + [correction(supersedes="goal-2", minute=43)])

    assert after.score == (1, 1), "a disallowed goal must stop counting"
    ids = [g.event_id for g in after.goals]
    assert "goal-2" in ids, "but it must stay visible in the timeline"
    disallowed = next(g for g in after.goals if g.event_id == "goal-2")
    assert disallowed.disallowed is True
    assert disallowed.correction_reason == "Offside in the build-up"
    assert disallowed.correction_authority == "VAR"
    assert disallowed.corrected_at_minute == 43


def test_reinstated_goal_restores_score(starting_log):
    log = starting_log + [
        correction(supersedes="goal-2", kind="disallow", minute=43),
        correction(supersedes="goal-2", kind="reinstate", minute=45,
                   reason="On review the defender played him onside"),
    ]
    state = project(log)
    assert state.score == (2, 1)
    goal = next(g for g in state.goals if g.event_id == "goal-2")
    assert goal.disallowed is False
    assert len(state.corrections) == 2, "both corrections stay in the log"


def test_reassignment_changes_scorer_not_score(starting_log):
    log = starting_log + [
        correction(supersedes="goal-2", kind="reassign", minute=43,
                   reason="Final touch reassigned after review",
                   payload={"player": {"id": "p99", "name": "Alvarez"}}),
    ]
    state = project(log)
    assert state.score == (2, 1), "attribution changed, the score did not"
    goal = next(g for g in state.goals if g.event_id == "goal-2")
    assert goal.scorer == "Alvarez"


def test_amend_revises_xg_without_touching_the_score(starting_log):
    log = starting_log + [
        correction(supersedes="goal-1", kind="amend", minute=25,
                   reason="xG revised", payload={"xg": 0.81}),
    ]
    state = project(log)
    assert state.score == (2, 1)
    goal = next(g for g in state.goals if g.event_id == "goal-1")
    assert goal.xg == pytest.approx(0.81)


def test_correction_out_of_order_still_projects_correctly(starting_log):
    """The correction arrives before the goal it corrects."""
    corr = correction(supersedes="goal-2", minute=43)
    scrambled = [corr] + starting_log
    assert project(scrambled).score == (1, 1)


def test_projection_is_identical_after_replaying_whole_log(starting_log):
    log = starting_log + [correction(supersedes="goal-2", minute=43)]
    once = project(log)
    twice = project(list(log) + list(log))  # every record delivered again
    assert once.score == twice.score
    assert [g.event_id for g in once.goals] == [g.event_id for g in twice.goals]


def test_double_applied_correction_is_idempotent(starting_log):
    corr = correction(supersedes="goal-2", minute=43)
    once = project(starting_log + [corr])
    twice = project(starting_log + [corr, corr, corr])
    assert once.score == twice.score
    assert len(twice.corrections) == 3, "the log keeps every record it was given"
    assert len(once.superseded) == len(twice.superseded) == 1


def test_later_decision_wins_over_earlier_one(starting_log):
    """Decision order, not arrival order, settles competing corrections."""
    reinstate_late = correction(supersedes="goal-2", kind="reinstate", minute=70,
                                reason="Overturned again", period=2)
    disallow_early = correction(supersedes="goal-2", kind="disallow", minute=43)
    assert project([*starting_log, reinstate_late, disallow_early]).score == (2, 1)
    assert project([*starting_log, disallow_early, reinstate_late]).score == (2, 1)


def test_was_it_ever_two_one(starting_log):
    """The question no mutable-row scores site can answer at all."""
    log = starting_log + [correction(supersedes="goal-2", minute=43)]
    assert project_until(log, 1, 41).score == (2, 0), "it was 2-0 at 41'"
    assert project_until(log, 1, 44).score == (1, 0), "and 1-0 once VAR ruled"
    assert project(log).score == (1, 1)


def test_red_card_counts_and_second_yellow_is_a_red(starting_log):
    log = starting_log + [
        ev(minute=70, type="Foul Committed", card="Second Yellow", team=AWAY, period=2),
        ev(minute=75, type="Bad Behaviour", card="Yellow Card", team=HOME, period=2),
    ]
    state = project(log)
    assert state.red_cards == (0, 1)
    assert len(state.cards) == 2


def test_own_goal_credits_the_other_team(starting_log):
    log = starting_log + [
        ev(minute=80, type="Own Goal Against", team=AWAY, period=2, event_id="og-1"),
    ]
    state = project(log)
    assert state.score == (3, 1), "France conceding an own goal scores for Argentina"
    og = next(g for g in state.goals if g.event_id == "og-1")
    assert og.own_goal is True


def test_shootout_is_not_part_of_the_scoreline():
    log = [
        ev(minute=0, type="Starting XI", team=HOME),
        ev(minute=0, type="Starting XI", team=AWAY),
        ev(minute=120, goal=True, xg=0.78, shot_type="Penalty", period=5, team=HOME),
        ev(minute=121, goal=True, xg=0.78, shot_type="Penalty", period=5, team=AWAY),
        ev(minute=122, goal=True, xg=0.78, shot_type="Penalty", period=5, team=HOME),
    ]
    state = project(log)
    assert state.score == (0, 0)
    assert state.shootout_score == (2, 1)
    assert "on penalties" in state.scoreline


# ---------------------------------------------------------------------------
# the property test that proves the model
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(60))
def test_projection_independent_of_arrival_order(starting_log, seed):
    """However events arrive, the projection is the same."""
    log = starting_log + [
        correction(supersedes="goal-2", minute=43),
        ev(minute=70, type="Foul Committed", card="Red Card", team=AWAY, period=2),
        ev(minute=80, goal=True, xg=0.4, player="Montiel", period=2, event_id="goal-4"),
    ]
    canonical = project(log)

    shuffled = list(log)
    random.Random(seed).shuffle(shuffled)
    assert project(shuffled).score == canonical.score
    assert project(shuffled).red_cards == canonical.red_cards
    assert sorted(g.event_id for g in project(shuffled).goals) == \
           sorted(g.event_id for g in canonical.goals)
    assert project(shuffled).superseded == canonical.superseded


try:
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st

    @settings(max_examples=200, deadline=None,
              suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        shuffle_seed=st.integers(min_value=0, max_value=2 ** 32),
        duplicates=st.integers(min_value=0, max_value=3),
    )
    def test_projection_is_a_set_function(shuffle_seed, duplicates):
        """Order-independent *and* duplicate-insensitive, over generated logs."""
        log = [
            ev(minute=0, type="Starting XI", team=HOME, event_id="xi-h"),
            ev(minute=0, type="Starting XI", team=AWAY, event_id="xi-a"),
            ev(minute=20, goal=True, xg=0.5, event_id="g1"),
            ev(minute=40, goal=True, xg=0.3, event_id="g2"),
            ev(minute=62, goal=True, xg=0.2, team=AWAY, period=2, event_id="g3"),
            correction(supersedes="g2", minute=43),
        ]
        expected = project(log)

        noisy = list(log) + list(log[:duplicates])
        random.Random(shuffle_seed).shuffle(noisy)
        got = project(noisy)

        assert got.score == expected.score
        assert got.superseded == expected.superseded
        assert got.shootout_score == expected.shootout_score

except ImportError:  # hypothesis is optional for a bare checkout
    pass
