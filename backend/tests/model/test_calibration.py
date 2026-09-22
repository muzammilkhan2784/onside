"""The calibration gate.

CI fails if the model gets worse. This is the difference between a model and
a notebook: the number is committed, and a change that regresses it cannot be
merged without someone deliberately moving the threshold.

The thresholds below are the measured result plus a small tolerance, recorded
in benchmarks/results/win_probability.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPORT = Path(__file__).resolve().parents[3] / "benchmarks" / "results" / "win_probability.json"

# Committed thresholds. Raising one is a deliberate act with a reason in the
# commit message, not a quiet edit.
MAX_BRIER = 0.42
MAX_LOG_LOSS = 0.72
MAX_INFERENCE_MS = 5.0
MAX_SERIES_RECOMPUTE_MS = 200.0


@pytest.fixture(scope="module")
def report() -> dict:
    if not REPORT.exists():
        pytest.skip(f"No calibration report at {REPORT}; run onside.models.train_wp")
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_brier_has_not_regressed(report):
    assert report["brier"]["lightgbm"] <= MAX_BRIER, (
        f"Brier {report['brier']['lightgbm']} is worse than the committed "
        f"threshold {MAX_BRIER}. Either the model got worse or the threshold "
        f"needs moving on purpose."
    )


def test_log_loss_has_not_regressed(report):
    assert report["log_loss"]["lightgbm"] <= MAX_LOG_LOSS


def test_model_beats_both_baselines(report):
    """A model that cannot beat "whoever is ahead wins" is not worth serving."""
    b = report["brier"]
    assert b["lightgbm"] < b["baseline_score_decides"]
    assert b["lightgbm"] < b["baseline_constant_prior"]


def test_model_beats_the_logistic_baseline(report):
    b = report["brier"]
    assert b["lightgbm"] < b["logistic_regression"]


def test_inference_is_fast_enough_to_serve(report):
    assert report["inference_ms_single_row"] < MAX_INFERENCE_MS


def test_full_series_recompute_is_fast_enough_for_a_correction(report):
    """A correction rebuilds the whole series on the hot path."""
    assert report["recompute_90_minute_series_ms"] < MAX_SERIES_RECOMPUTE_MS


def test_calibration_is_reported_by_minute_bucket(report):
    """Models are usually well calibrated late and badly early. Publish it
    rather than hiding it behind a single headline number."""
    buckets = report["calibration_by_minute"]
    assert len(buckets) >= 5
    early = next(b for b in buckets if b["bucket"] == "0-15")
    late = next(b for b in buckets if b["bucket"] == "75-90")
    assert late["brier"] < early["brier"], (
        "a live win-probability model should get sharper as the match runs out"
    )


def test_reliability_bins_track_observed_frequency(report):
    """The reliability diagram must actually be diagonal.

    Every bin holding a meaningful number of predictions should land within
    8 percentage points of the frequency it predicted.
    """
    off = [
        b for b in report["reliability"]
        if b["n"] >= 500 and abs(b["predicted"] - b["observed"]) > 0.08
    ]
    assert not off, f"poorly calibrated bins: {off}"


def test_the_split_is_time_based(report):
    """Guard the split itself - a random split would silently inflate all of
    the numbers above."""
    assert "time-based" in report["split"]["kind"]
    assert report["split"]["train_matches"] > 0
    assert report["split"]["test_matches"] > 0
