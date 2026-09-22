"""Unit tests for the pieces added around the core: metrics, the catalog's
tables and group inference, the codec, the replay schedule, the match
document's correction behaviour, and the projector's diff."""

from __future__ import annotations

import json

import pytest

from onside.domain.events import sorted_canonically
from onside.domain.match_state import DISALLOWED_GOAL, effective_events, project
from onside.domain.metrics import is_progressive, pass_network, team_metrics
from onside.feeds.statsbomb import normalise_match
from onside.ingest.catalog import infer_groups, season_tables
from onside.replay import build_timeline
from onside.replay.download import CACHE
from onside.replay.var_injector import inject
from onside.store import codec
from onside.workers.projector import diff

FINAL = 3869685


@pytest.fixture(scope="module")
def final_events():
    path = CACHE / "events" / f"{FINAL}.json"
    if not path.exists():
        pytest.skip("World Cup final not cached; run onside.replay.download")
    return normalise_match(json.loads(path.read_text(encoding="utf-8")), str(FINAL))


# ---------------------------------------------------------------- metrics

def test_ppda_lands_in_the_published_range_for_the_final(final_events):
    home, away = team_metrics(final_events, "779", "771", {"779": "Argentina", "771": "France"})
    # Published PPDA for elite international matches sits roughly between 6 and 16.
    assert 6 <= (home.ppda or 0) <= 16
    assert 6 <= (away.ppda or 0) <= 16
    assert home.possession + away.possession == pytest.approx(1.0)
    assert home.field_tilt + away.field_tilt == pytest.approx(1.0)
    assert home.goals == 3 and away.goals == 3, "shootout penalties are not goals"


def test_progressive_pass_definition():
    assert is_progressive((60, 40), (95, 40)), "25% closer to goal"
    assert is_progressive((90, 10), (105, 30)), "into the box counts regardless of distance"
    assert not is_progressive((60, 40), (62, 40))
    assert not is_progressive((60, 40), ())


def test_pass_network_stops_at_the_first_substitution(final_events):
    net = pass_network(final_events, "779")
    assert 8 <= len(net.nodes) <= 11, "roughly the starting eleven"
    assert net.until_minute < 90
    assert all(e["passes"] >= 3 for e in net.edges)


# ---------------------------------------------------------------- disallowed goals everywhere

def test_a_disallowed_goal_moves_every_number_not_only_the_score(final_events):
    corr = inject(final_events, match_id=str(FINAL), disallow=1, amend=0)
    eff = effective_events([*final_events, *corr])
    target = next(e for e in eff if e.event_id == corr[0].supersedes)
    assert target.shot is not None and target.shot.outcome == DISALLOWED_GOAL
    assert not target.is_goal
    home, _ = team_metrics(eff, "779", "771", {})
    assert home.goals == 2, "the metrics read the corrected events"
    assert home.shots_on_target >= 1, "the shot still happened and was on target"


# ---------------------------------------------------------------- codec

def test_codec_round_trips_every_event_of_a_real_match(final_events):
    for e in final_events:
        again = codec.event_from_dict(json.loads(json.dumps(codec.event_to_dict(e))))
        assert again == e


def test_codec_round_trips_corrections(final_events):
    for c in inject(final_events, match_id="x", disallow=1, amend=1):
        assert codec.correction_from_dict(codec.correction_to_dict(c)) == c


# ---------------------------------------------------------------- replay schedule

def test_schedule_is_monotonic_across_first_half_stoppage_time(final_events):
    schedule = build_timeline.build(final_events)
    ats = [s.at for s in schedule]
    assert ats == sorted(ats)
    # Every period-2 event is scheduled after every period-1 event, even though
    # first-half stoppage minutes (45+) overlap the second half's clock.
    last_p1 = max(s.at for s in schedule if s.record.period == 1)
    first_p2 = min(s.at for s in schedule if s.record.period == 2)
    assert first_p2 > last_p1


def test_a_correction_is_scheduled_after_the_goal_it_corrects(final_events):
    corr = inject(final_events, match_id=str(FINAL), disallow=1, amend=0)
    schedule = build_timeline.build(final_events, corr)
    goal_at = next(s.at for s in schedule if s.kind == "event" and s.record.event_id == corr[0].supersedes)
    corr_at = next(s.at for s in schedule if s.kind == "correction")
    assert corr_at > goal_at


# ---------------------------------------------------------------- catalog

def _card(mid, h, a, hs, as_, stage="Group Stage", date="2022-11-20"):
    return {"id": str(mid), "home": {"id": h, "name": h}, "away": {"id": a, "name": a},
            "score": [hs, as_], "stage": stage, "date": date, "kickoff": "16:00:00.000",
            "xg": [1.0, 1.0], "competition": {"id": "43", "name": "World Cup"}, "season": {"id": "106"}}


def test_groups_are_recovered_from_the_fixture_graph():
    cards = [
        _card(1, "A", "B", 1, 0), _card(2, "C", "D", 0, 0), _card(3, "A", "C", 2, 0),
        _card(4, "B", "D", 1, 1), _card(5, "E", "F", 3, 0, date="2022-11-21"), _card(6, "G", "H", 0, 1, date="2022-11-21"),
        _card(7, "E", "G", 1, 1, date="2022-11-22"), _card(8, "F", "H", 2, 2, date="2022-11-22"),
    ]
    groups = infer_groups(cards)
    teams = [sorted({c["home"]["id"] for c in g} | {c["away"]["id"] for c in g}) for g in groups]
    assert teams == [["A", "B", "C", "D"], ["E", "F", "G", "H"]]


def test_no_league_table_is_built_from_partial_coverage():
    # Two of a 20-team league's 380 fixtures - a table from these would be a lie.
    cards = [_card(1, "Barcelona", "Sevilla", 3, 0, stage="Regular Season"),
             _card(2, "Barcelona", "Girona", 2, 1, stage="Regular Season")]
    tables, note = season_tables(11, False, cards)
    assert tables == []
    assert "would be wrong" in note


def test_world_cup_groups_use_the_fifa_rule():
    cards = [_card(1, "A", "B", 1, 0), _card(2, "C", "D", 0, 0), _card(3, "A", "C", 2, 0),
             _card(4, "B", "D", 1, 1), _card(5, "A", "D", 0, 1), _card(6, "B", "C", 0, 0)]
    tables, note = season_tables(43, True, cards)
    assert len(tables) == 1
    assert tables[0]["ruleId"] == "FIFA_GROUP"
    assert "group letters" in note


# ---------------------------------------------------------------- projector diff

def _doc(score, corrections=(), minute=10, lines=("a",), timeline=()):
    return {"id": "live-1", "score": list(score), "shootout": None, "status": "live",
            "clock": {"period": 1, "minute": minute, "second": 0}, "stats": {}, "version": 1,
            "goals": [{"eventId": "g1", "player": "Di Maria", "minute": 35}],
            "corrections": list(corrections), "timeline": list(timeline),
            "winProbability": [{"minute": m, "p_home": 0.5, "p_draw": 0.3, "p_away": 0.2} for m in range(91)],
            "report": {"lines": list(lines), "lede": "x"}}


def test_diff_announces_a_correction_with_before_and_after_scores():
    before = _doc([2, 0], minute=36)
    corr = {"id": "c1", "supersedes": "g1", "kind": "disallow", "reason": "Offside in the build-up",
            "authority": "VAR", "headline": "Goal disallowed"}
    after = _doc([1, 0], corrections=[corr], minute=38, lines=("b",))
    msgs = diff(before, after)
    first = msgs[0]
    assert first["type"] == "correction_applied", "the correction is the headline of this update"
    assert first["scoreBefore"] == [2, 0] and first["scoreAfter"] == [1, 0]
    assert "ruled out" in first["message"]
    assert {m["type"] for m in msgs} >= {"state_changed", "report_regenerated"}


def test_diff_is_quiet_when_nothing_changed():
    d = _doc([1, 0])
    assert diff(d, d) == []


def test_live_state_never_knows_the_ending(final_events):
    """A report written at 40' must not name the eventual winner."""
    from onside.ingest.build import match_index
    from onside.ingest.document import build_document

    meta = next(m for m in match_index() if m["match_id"] == FINAL)
    partial = [e for e in sorted_canonically(final_events) if e.period == 1 and e.minute <= 40]
    doc = build_document(partial, meta, live=True)
    assert doc["score"] == [2, 0]
    assert doc["report"]["lede"] == "Argentina lead France 2-0 after 40 minutes."
    assert project(partial).score == (2, 0)
