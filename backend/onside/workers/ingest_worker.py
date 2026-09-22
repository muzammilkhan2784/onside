"""The ingest worker: shard stream -> event log -> projection -> diff.

The ingest log is partitioned by match into `bus.SHARDS` streams. A worker
holds a *lease* on each shard it serves (a Redis key with a TTL it keeps
renewing), so at any moment every match has exactly one writer. That single
writer keeps the match's log in memory:

* a batch of new records is appended to DynamoDB (conditionally - a
  redelivered event is a no-op) and to the in-memory log,
* the match is projected once per batch from memory - no re-reading thousands
  of items per event,
* the in-memory log is only ever rebuilt from DynamoDB on a cold start, after
  a lease changes hands, or when a replay restarts.

A message is acknowledged only after its match has been projected, so a worker
that dies mid-batch leaves its messages pending; its leases expire, another
worker takes the shards, and the reclaimer hands it the pending messages.

    python -m onside.workers.ingest_worker
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import redis

from ..domain.corrections import Correction
from ..domain.events import CanonicalEvent
from ..store import codec, repo
from ..streams import bus
from .projector import project_log

log = logging.getLogger("onside.worker")

BATCH = 512
BLOCK_MS = 1000
LEASE_TTL_MS = 15_000
RENEW_EVERY_S = 5.0


@dataclass
class MatchLog:
    """The authoritative in-memory log for one match on this worker."""

    events: dict[str, CanonicalEvent] = field(default_factory=dict)
    corrections: dict[str, Correction] = field(default_factory=dict)
    last_doc: dict[str, Any] | None = None

    @classmethod
    def load(cls, match_id: str) -> MatchLog:
        evs, corrs = repo.read_log(match_id)
        return cls(
            {e.event_id: e for e in evs},
            {c.correction_id: c for c in corrs},
            repo.get_document(match_id),
        )


class Worker:
    def __init__(self, r: redis.Redis, consumer: str) -> None:
        self.r = r
        self.consumer = consumer
        self.shards: set[int] = set()
        self.logs: dict[str, MatchLog] = {}
        self.last_renew = 0.0
        self.lock = threading.RLock()
        self.lost: set[int] = set()

    # ---- leases -----------------------------------------------------------
    def _lease_key(self, shard: int) -> str:
        return f"lease:ingest:{shard}"

    def balance(self) -> None:
        """Renew held leases and take any that are free.

        Leases are taken greedily, so one worker serves every shard when it is
        alone and the shards spread as more workers start (each new worker
        picks up whatever expires or was never taken).
        """
        now = time.time()
        if now - self.last_renew < RENEW_EVERY_S:
            return
        self.last_renew = now
        target = max(1, bus.SHARDS // max(1, self._live_workers()))
        for shard in range(bus.SHARDS):
            key = self._lease_key(shard)
            if shard in self.shards:
                # Renew only if we still hold it - a paused process must not
                # silently steal back a shard another worker took.
                ok = self.r.eval(
                    "if redis.call('get', KEYS[1]) == ARGV[1] then "
                    "return redis.call('pexpire', KEYS[1], ARGV[2]) else return 0 end",
                    1,
                    key,
                    self.consumer,
                    LEASE_TTL_MS,
                )
                if not ok:
                    self._drop_shard(shard)
            elif len(self.shards) < target and self.r.set(
                key, self.consumer, nx=True, px=LEASE_TTL_MS
            ):
                self.shards.add(shard)
                log.info("%s took shard %d", self.consumer, shard)
        # Give back anything above a fair share so a newly started worker gets
        # shards instead of idling until this one dies.
        while len(self.shards) > target:
            shard = max(self.shards)
            self.r.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) "
                "else return 0 end",
                1,
                self._lease_key(shard),
                self.consumer,
            )
            self._drop_shard(shard)
        self.r.set(f"worker:alive:{self.consumer}", "1", px=LEASE_TTL_MS)

    def _live_workers(self) -> int:
        return max(1, sum(1 for _ in self.r.scan_iter("worker:alive:*", count=100)))

    def _drop_shard(self, shard: int) -> None:
        with self.lock:
            self.shards.discard(shard)
            self.lost.add(shard)
        log.info("%s lost shard %d", self.consumer, shard)

    def _forget_lost(self) -> None:
        """Called from the processing loop: drop in-memory logs for shards the
        heartbeat gave up, so they are reloaded if the shard ever comes back."""
        with self.lock:
            lost, self.lost = self.lost, set()
        for mid in [m for m in self.logs if bus.shard_of(m) in lost]:
            del self.logs[mid]

    def heartbeat(self, stop: threading.Event) -> None:
        """Renew leases on a timer, independent of how long a batch takes.
        A slow batch must never let a lease lapse into a second writer."""
        while not stop.wait(1.0):
            try:
                with self.lock:
                    self.balance()
            except (redis.ConnectionError, redis.TimeoutError):
                log.warning("heartbeat could not reach redis")

    def release(self) -> None:
        for shard in list(self.shards):
            self.r.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) "
                "else return 0 end",
                1,
                self._lease_key(shard),
                self.consumer,
            )
        self.r.delete(f"worker:alive:{self.consumer}")

    # ---- work -------------------------------------------------------------
    def handle(self, messages: list[tuple[str, dict[str, str]]]) -> list[str]:
        """Apply a batch. Returns the message ids that are safe to acknowledge."""
        touched: dict[str, list[str]] = defaultdict(list)
        new_events: list[CanonicalEvent] = []
        new_corrections: list[Correction] = []
        for msg_id, fields in messages:
            match_id = fields.get("match", "")
            kind = fields.get("kind", "")
            body: dict[str, Any] = json.loads(fields.get("body", "{}"))
            try:
                if kind == "control" and body.get("action") == "reset":
                    self.logs.pop(match_id, None)
                    touched.setdefault(match_id, []).append(msg_id)
                    continue
                mlog = self.logs.get(match_id)
                if mlog is None:
                    mlog = self.logs[match_id] = MatchLog.load(match_id)
                if kind == "event":
                    e = codec.event_from_dict(body)
                    if e.event_id not in mlog.events:
                        new_events.append(e)
                        mlog.events[e.event_id] = e
                elif kind == "correction":
                    c = codec.correction_from_dict(body)
                    if c.correction_id not in mlog.corrections:
                        new_corrections.append(c)
                        mlog.corrections[c.correction_id] = c
            except Exception:
                log.exception("failed to append %s for %s; leaving it pending", msg_id, match_id)
                continue
            touched[match_id].append(msg_id)

        try:
            repo.append_batch(new_events, new_corrections)
        except Exception:
            # Nothing is acknowledged if the log write failed; drop the
            # in-memory copies so the retry starts from what is durable.
            log.exception(
                "failed to append a batch of %d records", len(new_events) + len(new_corrections)
            )
            for mid in touched:
                self.logs.pop(mid, None)
            return []

        acked: list[str] = []
        for match_id, ids in touched.items():
            mlog = self.logs.get(match_id)
            if mlog is None or not mlog.events:
                acked.extend(ids)
                continue
            try:
                doc = project_log(
                    match_id,
                    list(mlog.events.values()),
                    list(mlog.corrections.values()),
                    before=mlog.last_doc,
                    r=self.r,
                )
                if doc is not None:
                    mlog.last_doc = doc
                acked.extend(ids)
            except repo.VersionConflict:
                log.warning("version conflict on %s - reloading its log", match_id)
                self.logs.pop(match_id, None)
            except Exception:
                log.exception(
                    "projection failed for %s; %d messages stay pending", match_id, len(ids)
                )
        return acked

    def run(self) -> None:
        bus.ensure_groups(self.r)
        stopping = False

        def stop(*_: Any) -> None:
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        log.info("worker %s starting; %d shards", self.consumer, bus.SHARDS)
        halt = threading.Event()
        with self.lock:
            self.balance()
        threading.Thread(
            target=self.heartbeat, args=(halt,), daemon=True, name="lease-heartbeat"
        ).start()
        try:
            while not stopping:
                try:
                    self._forget_lost()
                    with self.lock:
                        shards = sorted(self.shards)
                    if not shards:
                        time.sleep(1)
                        continue
                    streams = {bus.shard_stream(s): ">" for s in shards}
                    resp = self.r.xreadgroup(
                        bus.INGEST_GROUP, self.consumer, streams, count=BATCH, block=BLOCK_MS
                    )
                except (redis.ConnectionError, redis.TimeoutError):
                    log.warning("redis unavailable; retrying in 2s")
                    time.sleep(2)
                    continue
                for stream, messages in resp or []:
                    t0 = time.perf_counter()
                    acked = self.handle(messages)
                    if acked:
                        self.r.xack(stream, bus.INGEST_GROUP, *acked)
                    log.info(
                        "%s: applied %d/%d in %.0f ms",
                        stream,
                        len(acked),
                        len(messages),
                        (time.perf_counter() - t0) * 1000,
                    )
        finally:
            halt.set()
            with self.lock:
                self.release()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    r = redis.Redis.from_url(bus.settings().redis_url, decode_responses=True)
    Worker(r, f"{socket.gethostname()}-{os.getpid()}").run()


if __name__ == "__main__":
    main()
