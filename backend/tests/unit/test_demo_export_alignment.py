"""Guard against train/serve skew in the browser demo.

The demo rebuilds the feature vector in JavaScript from per-minute arrays. If
those arrays disagree by even one minute with what `match_minute_rows`
produces for training, the browser serves the model inputs it has never seen.
That happened once: the export included the current minute's events while the
trainer excluded them, and the visible symptom was a nonsense kick-off
probability. This test pins the two together.
"""

from __future__ import annotations

import json

import pytest

from onside.feeds.statsbomb import normalise_match
from onside.models.features import FEATURE_NAMES, match_minute_rows
from onside.replay.download import CACHE
from onside.replay.export_demo import build_payload

DEMO_MATCH = 3869685  # the 2022 World Cup final


@pytest.fixture(scope="module")
def payload() -> dict:
    if not (CACHE / "events" / f"{DEMO_MATCH}.json").exists():
        pytest.skip("StatsBomb events not cached; run onside.replay.download")
    return build_payload(DEMO_MATCH, {"competition": "FIFA World Cup 2022"})


def test_exported_minutes_match_the_training_feature_builder(payload):
    raw = json.loads((CACHE / "events" / f"{DEMO_MATCH}.json").read_text(encoding="utf-8"))
    events = normalise_match(raw, str(DEMO_MATCH))
    rows = match_minute_rows(
        events,
        home_id=payload["match"]["homeId"],
        away_id=payload["match"]["awayId"],
        match_id=str(DEMO_MATCH),
        elo_diff=0.0,
        is_neutral_venue=True,
    )
    mins = payload["minutes"]
    idx = {n: i for i, n in enumerate(FEATURE_NAMES)}

    for row in rows:
        m = row.minute
        f = row.features
        assert mins["xgH"][m] - mins["xgA"][m] == pytest.approx(f[idx["xg_diff"]], abs=1e-3), \
            f"xg_diff disagrees at minute {m}"
        assert mins["shH"][m] - mins["shA"][m] == f[idx["shots_diff"]], \
            f"shots_diff disagrees at minute {m}"
        assert mins["sotH"][m] - mins["sotA"][m] == f[idx["shots_on_target_diff"]], \
            f"shots_on_target_diff disagrees at minute {m}"
        assert mins["possDiff"][m] == pytest.approx(f[idx["possession_diff"]], abs=1e-3), \
            f"possession_diff disagrees at minute {m}"


def test_no_state_leaks_from_the_current_minute(payload):
    """Everything at minute 0 must be zero: nothing has happened yet."""
    mins = payload["minutes"]
    for key in ("xgH", "xgA", "shH", "shA", "sotH", "sotA", "possDiff"):
        assert mins[key][0] == 0, f"{key} is non-zero before kick-off"


def test_the_demo_correction_actually_changes_the_scoreline(payload):
    """A correction that does not move the score would make the demo a lie."""
    disallow = next(c for c in payload["corrections"] if c["kind"] == "disallow")
    target = next(g for g in payload["goals"] if g["id"] == disallow["supersedes"])
    assert target["period"] <= 2, "the demo's disallowed goal must be in regulation"
    assert disallow["decidedAt"] > target["minute"], "the decision arrives after the goal"
    assert disallow["synthesised"] is True, "synthesised corrections must be flagged"


def test_freeze_frames_survive_the_export(payload):
    with_ff = [s for s in payload["shots"] if s["freeze"]]
    assert with_ff, "the shot map's freeze-frames are the point of the 360 data"
    sample = with_ff[0]
    assert all(0 <= a["x"] <= 120 and 0 <= a["y"] <= 80 for a in sample["freeze"])
