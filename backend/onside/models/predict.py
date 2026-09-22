"""Serve the win-probability model.

Loaded once at process start. A single prediction must be under 5ms and a
full-match recompute under 200ms, because both happen on the hot path when a
correction lands.

**Range:** the model is trained on regulation minutes (0-90) with a three-class
target - home win, draw, away win - decided at the end of 90 minutes. It is
deliberately not applied to extra time or penalties, where "draw" stops
meaning anything. The series therefore covers regulation and the UI says so.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from ..config import settings
from ..domain.events import CanonicalEvent
from .features import FEATURE_NAMES, REGULATION_MINUTES, match_minute_rows

MODEL_PATH = settings().model_dir / "wp_lgbm.txt"


@lru_cache(maxsize=1)
def _booster(path: str = "") -> Any:
    import lightgbm as lgb

    p = Path(path) if path else MODEL_PATH
    if not p.exists():
        raise FileNotFoundError(f"No model at {p}. Run `python -m onside.models.train_wp` first.")
    return lgb.Booster(model_file=str(p))


def predict(features: Sequence[Sequence[float]]) -> np.ndarray:
    """(n, n_features) -> (n, 3) probabilities over home / draw / away."""
    arr = np.asarray(features, dtype=np.float64).reshape(-1, len(FEATURE_NAMES))
    return _booster().predict(arr)  # type: ignore[no-any-return]


def series_for_match(
    events: Sequence[CanonicalEvent],
    *,
    home_id: str,
    away_id: str,
    match_id: str = "",
    elo_diff: float = 0.0,
    is_neutral_venue: bool = True,
) -> list[dict[str, float]]:
    """The per-minute win-probability series for one match.

    This is what a correction invalidates: change the log, rebuild the state,
    call this again.
    """
    rows = match_minute_rows(
        events,
        home_id=home_id,
        away_id=away_id,
        match_id=match_id,
        elo_diff=elo_diff,
        is_neutral_venue=is_neutral_venue,
    )
    probs = predict([r.features for r in rows])
    return [
        {
            "minute": r.minute,
            "p_home": round(float(p[0]), 4),
            "p_draw": round(float(p[1]), 4),
            "p_away": round(float(p[2]), 4),
        }
        for r, p in zip(rows, probs, strict=True)
    ]


def timed_series(
    events: Sequence[CanonicalEvent], **kw: Any
) -> tuple[list[dict[str, float]], float]:
    """The series plus how long it took, for the correction benchmark."""
    t0 = time.perf_counter()
    out = series_for_match(events, **kw)
    return out, (time.perf_counter() - t0) * 1000


__all__ = ["predict", "series_for_match", "timed_series", "REGULATION_MINUTES"]
