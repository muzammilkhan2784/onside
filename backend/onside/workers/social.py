"""Collect public posts about the current football, every two minutes
(every five on the free-tier AWS deployment, where a schedule runs it).

Reads the fixtures snapshot (from the fixtures worker), works out what to look
for (social/topics.py), asks every source that is switched on, and stores what
passes the filters. A failing source is recorded as failing - with a message
people can read - and the others carry on.

    python -m onside.workers.social
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from ..social import store, topics
from ..social.base import Source
from ..social.sources import Bluesky, Mastodon, Reddit, X
from ..streams import bus
from . import fixtures

log = logging.getLogger("onside.social")

POLL_S = int(os.environ.get("ONSIDE_SOCIAL_EVERY_S", "120"))


def sources(r: Any) -> list[Source]:
    return [Bluesky(), Mastodon(), Reddit(), X(r=r)]


def _safe(exc: Exception) -> str:
    """An error message fit for the dashboard: the type and the gist, never a
    URL (which could carry a query) or a credential."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (403, 429):
        return (
            f"The network is limiting requests from this server (HTTP {status}). "
            f"Retrying in {POLL_S // 60} minutes."
        )
    text = f"HTTP {status}" if status else str(exc).split("\n")[0]
    if "http" in text or "Bearer" in text:
        text = type(exc).__name__
    return f"Last attempt failed ({text[:140]}). Retrying in {POLL_S // 60} minutes."


def cycle(r: Any, srcs: list[Source]) -> dict[str, int]:
    snap = json.loads(r.get(fixtures.KEY) or "{}")
    p = topics.plan(snap.get("matches") or [])
    store.set_topics(
        r,
        [
            {"id": t.id, "label": t.label, "kind": t.kind, "competition": t.competition, **t.meta}
            for t in p.topics
        ],
    )
    counts: dict[str, int] = {}
    for s in srcs:
        state, message = s.state()
        if state != "on":
            store.set_source(r, s.name, state, message)
            continue
        try:
            posts = s.collect(p)
            counts[s.name] = store.save(r, posts)
            store.set_source(r, s.name, "on", message, counts[s.name])
        except Exception as exc:  # noqa: BLE001 - one source failing must not stop the rest
            log.warning("%s: %s", s.name, exc)
            store.set_source(r, s.name, "error", _safe(exc))
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per cycle, not per request
    r = bus.sync_client()
    srcs = sources(r)
    # Give the fixtures worker a moment on a cold start, so the first cycle
    # already knows which matches to look for.
    for _ in range(30):
        if json.loads(r.get(fixtures.KEY) or "{}").get("matches"):
            break
        time.sleep(2)
    while True:
        started = time.time()
        counts = cycle(r, srcs)
        log.info("social: %s", ", ".join(f"{k} {v}" for k, v in counts.items()) or "nothing on")
        time.sleep(max(5.0, POLL_S - (time.time() - started)))


if __name__ == "__main__":
    main()
