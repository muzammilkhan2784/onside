"""Reclaim work a dead worker left behind.

A worker that crashes after reading a batch but before acknowledging it leaves
those messages in the consumer group's pending list forever. The reclaimer
periodically runs XAUTOCLAIM for anything idle longer than `MIN_IDLE_MS`,
takes ownership, and applies it with the same handler the workers use. Appends
are idempotent and projections are versioned, so reprocessing a message that
had in fact been applied is harmless.

    python -m onside.workers.reclaimer
"""

from __future__ import annotations

import logging
import time

import redis

from ..streams import bus
from .ingest_worker import Worker

log = logging.getLogger("onside.reclaimer")

MIN_IDLE_MS = 30_000
INTERVAL_S = 10
CONSUMER = "reclaimer"


def reclaim_once(r: redis.Redis, min_idle_ms: int = MIN_IDLE_MS) -> int:
    """One sweep over every shard. Returns how many messages were recovered.

    The reclaimer applies recovered work with a fresh worker whose in-memory
    logs start empty, so it always rebuilds from the store: slower than the
    hot path, and correct regardless of what the dead worker had in memory.
    """
    recovered = 0
    applier = Worker(r, CONSUMER)
    for stream in bus.ALL_SHARD_STREAMS:
        start = "0-0"
        while True:
            nxt, claimed, *_ = r.xautoclaim(
                stream,
                bus.INGEST_GROUP,
                CONSUMER,
                min_idle_time=min_idle_ms,
                start_id=start,
                count=256,
            )
            live = [(mid, fields) for mid, fields in claimed if fields]
            if live:
                acked = applier.handle(live)
                if acked:
                    r.xack(stream, bus.INGEST_GROUP, *acked)
                    recovered += len(acked)
            # Entries trimmed from the stream come back with no fields; ack them
            # so they stop occupying the pending list.
            dead = [mid for mid, fields in claimed if not fields]
            if dead:
                r.xack(stream, bus.INGEST_GROUP, *dead)
            if nxt in ("0-0", b"0-0"):
                break
            start = nxt
    return recovered


def run() -> None:
    r = bus.sync_client()
    bus.ensure_groups(r)
    log.info("reclaiming messages idle for more than %ds", MIN_IDLE_MS // 1000)
    while True:
        try:
            n = reclaim_once(r)
            if n:
                log.warning("recovered %d messages from a stalled worker", n)
        except redis.ConnectionError:
            log.warning("redis unavailable")
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    run()
