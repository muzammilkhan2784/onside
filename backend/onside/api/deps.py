"""Shared request helpers: cached catalog reads and match lookup."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

from ..store import repo
from .errors import not_found

T = TypeVar("T")

_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def cached(key: str, ttl: float, fn: Callable[[], T]) -> T:
    """A tiny TTL cache for catalog data that changes only when the archive is
    reseeded. Per process; each API task warms its own."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]  # type: ignore[no-any-return]
    value = fn()
    with _lock:
        _cache[key] = (now, value)
    return value


def catalog(kind: str, key: str = "all", ttl: float = 300) -> Any:
    return cached(f"catalog:{kind}:{key}", ttl, lambda: repo.get_catalog(kind, key))


def match_state(match_id: str) -> dict[str, Any]:
    state = repo.get_part(match_id, "STATE")
    if state is None:
        hint = (
            "Replays use ids like live-3869685 and exist once that replay has been started."
            if match_id.startswith("live-")
            else "Match ids are StatsBomb ids, e.g. 3869685."
        )
        raise not_found("match", match_id, hint)
    return state


def match_part(match_id: str, part: str) -> dict[str, Any]:
    body = repo.get_part(match_id, part)
    if body is None:
        match_state(match_id)  # raises a clean 404 if the match itself is missing
        return {}
    return body
