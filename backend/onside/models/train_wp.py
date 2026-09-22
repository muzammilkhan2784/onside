"""Train and evaluate the live win-probability model.

Design decisions worth defending:

* **Split by date, not by row.** Train on every match before the cutoff,
  test on everything after. Splitting rows at random would leak: 91 rows from
  the same match are near-duplicates, and a random split puts most of them on
  both sides of the line. An earlier version split by *competition* instead,
  which left every test team on a default Elo rating and produced a model
  worse than "whoever is ahead wins" - the numbers caught it.
* **Regulation only.** The target is the result at the end of 90 minutes, so
  "draw" keeps its meaning. Extra-time rows would silently change the
  question being asked.
* **Evaluation written before tuning.** Brier against two baselines, log loss,
  a reliability diagram and calibration by minute bucket. If you tune first
  you tune against a number you have not defined.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..config import ROOT, settings
from .features import FEATURE_NAMES

MODEL_DIR = settings().model_dir
BENCH_DIR = ROOT / "benchmarks" / "results"
CLASSES = ("home_win", "draw", "away_win")


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


def multiclass_brier(probs: np.ndarray, y: np.ndarray) -> float:
    """Mean squared error against the one-hot truth, summed over classes."""
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(y)), y] = 1.0
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))


def log_loss(probs: np.ndarray, y: np.ndarray, eps: float = 1e-12) -> float:
    p = np.clip(probs[np.arange(len(y)), y], eps, 1.0)
    return float(-np.mean(np.log(p)))


def reliability(probs: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict[str, float]]:
    """Predicted vs observed frequency, pooled over the three classes."""
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(y)), y] = 1.0
    p = probs.ravel()
    t = onehot.ravel()
    edges = np.linspace(0.0, 1.0, bins + 1)
    out = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (p >= lo) & (p < hi if i < bins - 1 else p <= hi)
        if not mask.any():
            continue
        out.append(
            {
                "bin_lo": round(float(lo), 3),
                "bin_hi": round(float(hi), 3),
                "predicted": round(float(p[mask].mean()), 4),
                "observed": round(float(t[mask].mean()), 4),
                "n": int(mask.sum()),
            }
        )
    return out


def calibration_by_minute(
    probs: np.ndarray, y: np.ndarray, minutes: np.ndarray
) -> list[dict[str, float]]:
    """Models are usually well calibrated at 80' and badly at 10'. Show it."""
    out = []
    for lo in range(0, 90, 15):
        mask = (minutes >= lo) & (minutes < lo + 15)
        if not mask.any():
            continue
        out.append(
            {
                "bucket": f"{lo}-{lo + 15}",
                "brier": round(multiclass_brier(probs[mask], y[mask]), 4),
                "n": int(mask.sum()),
            }
        )
    return out


def _score_decides_baseline(Xtr: np.ndarray, ytr: np.ndarray, Xte: np.ndarray) -> np.ndarray:
    """ "Whoever is ahead wins." Empirical P(outcome | sign(score_diff))."""
    sd_tr = np.sign(Xtr[:, FEATURE_NAMES.index("score_diff")])
    sd_te = np.sign(Xte[:, FEATURE_NAMES.index("score_diff")])
    table: dict[float, np.ndarray] = {}
    for s in (-1.0, 0.0, 1.0):
        mask = sd_tr == s
        if mask.any():
            table[s] = np.bincount(ytr[mask], minlength=3) / mask.sum()
        else:
            table[s] = np.ones(3) / 3
    return np.vstack([table[s] for s in sd_te])


# ---------------------------------------------------------------------------
# export for the browser
# ---------------------------------------------------------------------------


def export_trees(booster: Any, path: Path) -> dict[str, Any]:
    """Dump LightGBM to a compact JSON the browser demo can evaluate.

    The demo runs the *real* model, not a lookalike: when a VAR correction
    lands in the browser, the whole win-probability series is genuinely
    recomputed through these trees.
    """
    dump = booster.dump_model()

    def compact(node: dict[str, Any]) -> Any:
        if "leaf_value" in node:
            return round(float(node["leaf_value"]), 9)
        return {
            "f": int(node["split_feature"]),
            # Thresholds are NOT rounded. LightGBM encodes a "zero versus
            # positive" split as a threshold of ~1e-35, and rounding that to a
            # few decimal places collapses it to +/-0.0, which flips the
            # routing for any feature that is exactly zero. That is the
            # kick-off state of every match - score_diff, red_card_diff and
            # xg_diff are all 0 - so the browser disagreed with the served
            # model precisely where a viewer looks first.
            "t": float(node["threshold"]),
            "d": node.get("default_left", True),
            "l": compact(node["left_child"]),
            "r": compact(node["right_child"]),
        }

    trees = [compact(t["tree_structure"]) for t in dump["tree_info"]]
    payload = {
        "n_classes": 3,
        "classes": list(CLASSES),
        "features": list(FEATURE_NAMES),
        "trees": trees,
        "n_trees": len(trees),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return payload


def split_by_date(data: dict[str, np.ndarray], holdout: float = 0.2) -> tuple:
    """Train on the earlier matches, test on the later ones.

    The cutoff is placed on a match-date boundary so no match straddles the
    split: 91 rows from one match are near-duplicates of each other, and
    letting them land on both sides is the classic way to report a score the
    model has not earned.
    """
    dates = data["date"]
    order = np.argsort(dates, kind="stable")
    cutoff_idx = int(len(order) * (1 - holdout))
    cutoff_date = str(dates[order[cutoff_idx]])
    train_mask = dates < cutoff_date
    test_mask = ~train_mask
    return (
        data["X"][train_mask].astype(np.float64),
        data["y"][train_mask].astype(np.int64),
        data["X"][test_mask].astype(np.float64),
        data["y"][test_mask].astype(np.int64),
        cutoff_date,
        len(set(data["match_id"][train_mask].tolist())),
        len(set(data["match_id"][test_mask].tolist())),
    )


def main() -> dict[str, Any]:
    import lightgbm as lgb

    from .dataset import load

    print("Loading the archive-wide dataset...", flush=True)
    data = load()
    Xtr, ytr, Xte, yte, cutoff, n_tr, n_te = split_by_date(data)
    print(f"  train {Xtr.shape[0]:,} rows / {n_tr:,} matches before {cutoff}", flush=True)
    print(f"  test  {Xte.shape[0]:,} rows / {n_te:,} matches from {cutoff}", flush=True)

    minutes = Xte[:, FEATURE_NAMES.index("minute")]

    # --- baselines, computed before the model exists ---
    prior = np.bincount(ytr, minlength=3) / len(ytr)
    p_prior = np.tile(prior, (len(yte), 1))
    p_score = _score_decides_baseline(Xtr, ytr, Xte)

    # --- baseline model: multinomial logistic regression ---
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(Xtr)
    lr = LogisticRegression(max_iter=2000, C=1.0)
    lr.fit(scaler.transform(Xtr), ytr)
    p_lr = lr.predict_proba(scaler.transform(Xte))

    # --- main model ---
    train_set = lgb.Dataset(Xtr, label=ytr, feature_name=list(FEATURE_NAMES))
    valid_set = lgb.Dataset(Xte, label=yte, reference=train_set)
    params = {
        "objective": "multiclass",
        "num_class": 3,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "max_depth": 6,
        "min_data_in_leaf": 400,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "lambda_l2": 5.0,
        "verbose": -1,
        "seed": 7,
    }
    booster = lgb.train(
        params,
        train_set,
        num_boost_round=1200,
        valid_sets=[valid_set],
        callbacks=[lgb.early_stopping(60, verbose=False), lgb.log_evaluation(0)],
    )
    p_gbm = booster.predict(Xte, num_iteration=booster.best_iteration)

    # --- inference latency, single row, the way it is served ---
    one = Xte[:1]
    booster.predict(one)  # warm
    t0 = time.perf_counter()
    for _ in range(200):
        booster.predict(one, num_iteration=booster.best_iteration)
    per_call_ms = (time.perf_counter() - t0) / 200 * 1000

    # --- full 90-minute series recompute, as a correction would trigger ---
    series = Xte[:91]
    t0 = time.perf_counter()
    for _ in range(20):
        booster.predict(series, num_iteration=booster.best_iteration)
    series_ms = (time.perf_counter() - t0) / 20 * 1000

    report: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%d"),
        "split": {
            "kind": "time-based, on a match-date boundary",
            "cutoff_date": cutoff,
            "train_rows": int(Xtr.shape[0]),
            "train_matches": n_tr,
            "test_rows": int(Xte.shape[0]),
            "test_matches": n_te,
            "source": "StatsBomb Open Data, every competition-season published",
        },
        "features": list(FEATURE_NAMES),
        "best_iteration": int(booster.best_iteration),
        "brier": {
            "lightgbm": round(multiclass_brier(p_gbm, yte), 4),
            "logistic_regression": round(multiclass_brier(p_lr, yte), 4),
            "baseline_constant_prior": round(multiclass_brier(p_prior, yte), 4),
            "baseline_score_decides": round(multiclass_brier(p_score, yte), 4),
        },
        "log_loss": {
            "lightgbm": round(log_loss(p_gbm, yte), 4),
            "logistic_regression": round(log_loss(p_lr, yte), 4),
            "baseline_constant_prior": round(log_loss(p_prior, yte), 4),
            "baseline_score_decides": round(log_loss(p_score, yte), 4),
        },
        "reliability": reliability(p_gbm, yte),
        "calibration_by_minute": calibration_by_minute(p_gbm, yte, minutes),
        "inference_ms_single_row": round(per_call_ms, 3),
        "recompute_90_minute_series_ms": round(series_ms, 3),
        "feature_importance": {
            name: int(v)
            for name, v in zip(
                FEATURE_NAMES,
                booster.feature_importance(importance_type="gain").round(),
                strict=True,
            )
        },
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(MODEL_DIR / "wp_lgbm.txt"), num_iteration=booster.best_iteration)
    payload = export_trees(booster, MODEL_DIR / "wp_lgbm.json")
    report["exported_trees"] = payload["n_trees"]

    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    (BENCH_DIR / "win_probability.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k
                in (
                    "brier",
                    "log_loss",
                    "inference_ms_single_row",
                    "recompute_90_minute_series_ms",
                    "best_iteration",
                    "exported_trees",
                )
            },
            indent=2,
        )
    )
    return report


if __name__ == "__main__":
    main()
