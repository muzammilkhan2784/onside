"""The exported model must be the served model.

The demo page evaluates the LightGBM trees in JavaScript so that a correction
genuinely recomputes the win-probability series in the browser. That is only
honest if the exported trees produce the same numbers as the booster.

This test exists because they once did not. The exporter rounded split
thresholds to six decimal places, and LightGBM encodes a "zero versus
positive" split with a threshold of about 1e-35. Rounding collapsed it to
+/-0.0 and flipped the routing for any feature that was exactly zero - which
is every feature at kick-off. Random inputs agreed to seven decimal places
and the page still showed a nonsense probability at minute 0.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
MODEL_TXT = ROOT / "models" / "wp_lgbm.txt"
MODEL_JSON = ROOT / "models" / "wp_lgbm.json"

TOLERANCE = 1e-6


@pytest.fixture(scope="module")
def pair():
    if not (MODEL_TXT.exists() and MODEL_JSON.exists()):
        pytest.skip("No trained model; run onside.models.train_wp")
    import lightgbm as lgb

    return lgb.Booster(model_file=str(MODEL_TXT)), json.loads(
        MODEL_JSON.read_text(encoding="utf-8")
    )


def _evaluate(spec: dict, x) -> list[float]:
    """The JavaScript evaluator, transcribed. Keep the two in step."""
    k = spec["n_classes"]
    raw = [0.0] * k
    for i, tree in enumerate(spec["trees"]):
        node = tree
        while isinstance(node, dict):
            node = node["l"] if x[node["f"]] <= node["t"] else node["r"]
        raw[i % k] += node
    top = max(raw)
    exps = [math.exp(v - top) for v in raw]
    total = sum(exps)
    return [v / total for v in exps]


def test_export_matches_the_booster_on_random_inputs(pair):
    booster, spec = pair
    n = len(spec["features"])
    rows = np.random.RandomState(0).uniform(-3, 3, size=(50, n))
    rows[:, 0] = np.random.RandomState(1).randint(0, 91, 50)
    mine = np.array([_evaluate(spec, list(r)) for r in rows])
    assert np.abs(mine - booster.predict(rows)).max() < TOLERANCE


def test_export_matches_the_booster_when_features_are_exactly_zero(pair):
    """The case the rounding bug broke: kick-off, and every level scoreline."""
    booster, spec = pair
    n = len(spec["features"])
    rows = []
    for score_diff in (-2, -1, 0, 1, 2):
        for minute in (0, 1, 20, 45, 70, 89, 90):
            r = np.zeros(n)
            r[0] = minute
            r[1] = max(90 - minute, 0)
            r[2] = score_diff
            rows.append(r)
    rows = np.asarray(rows)
    mine = np.array([_evaluate(spec, list(r)) for r in rows])
    assert np.abs(mine - booster.predict(rows)).max() < TOLERANCE


def test_thresholds_keep_full_precision(pair):
    """Guard the fix directly: near-zero thresholds must survive the export."""
    _, spec = pair
    tiny = []

    def walk(node):
        if not isinstance(node, dict):
            return
        t = node["t"]
        if t != 0.0 and abs(t) < 1e-6:
            tiny.append(t)
        walk(node["l"])
        walk(node["r"])

    for tree in spec["trees"]:
        walk(tree)
    assert tiny, (
        "no sub-1e-6 thresholds survived the export - they have been rounded "
        "away, and zero-valued features will route the wrong way"
    )


def test_kickoff_probability_is_plausible(pair):
    """A neutral-venue match at 0-0 should not favour either side heavily.

    A sanity floor, not a calibration check: the numbers that matter live in
    tests/model/test_calibration.py. This catches the class of bug where the
    page looks broken to anyone who presses Restart.
    """
    _, spec = pair
    n = len(spec["features"])
    x = [0.0] * n
    x[1] = 90.0
    x[spec["features"].index("is_neutral_venue")] = 1.0
    p_home, p_draw, p_away = _evaluate(spec, x)
    assert 0.25 < p_home < 0.65, p_home
    assert 0.15 < p_draw < 0.40, p_draw
    assert 0.15 < p_away < 0.55, p_away
    assert p_home > p_away, "home advantage should not invert at kick-off"
