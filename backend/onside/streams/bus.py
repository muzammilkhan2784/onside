"""Redis Streams and pub/sub, the two halves of the realtime spine.

    feed / replay ──XADD──▶ stream "ingest" ──XREADGROUP──▶ ingest workers
                                                              │ append + project
                                                              ▼
    WebSocket gateways ◀──SUBSCRIBE── channel "match:<id>" ◀──PUBLISH (diff)

* **Streams** carry work. A consumer group splits it across workers; a message
  is only removed from the pending list when a worker XACKs it, so a crashed
  worker's messages are reclaimed (see workers/reclaimer.py) instead of lost.
* **Pub/sub** carries fan-out to browsers. It is fire-and-forget, so every
  published message also gets a per-channel sequence number and is mirrored
  into a capped stream `chanlog:<channel>`. A reconnecting client sends the
  last seq it saw and is replayed everything after it.
"""

from __future__ import annotations

import json
import time
import zlib
from functools import lru_cache
from typing import Any

import redis
import redis.asyncio as aioredis

from ..config import settings

INGEST_GROUP = "projectors"
#: The ingest log is partitioned by match, like a Kafka topic. Each shard has
#: exactly one owning worker at a time (see workers/lease.py), so every match
#: has a single writer that can keep its log in memory.
SHARDS = 8
REPLAY_CONTROL_STREAM = "replay:control"
CHANLOG_MAXLEN = 1000
ACTIVE_REPLAYS = "replays:active"
#: A replay thread stamps its state every tick. One that has not been heard
#: from in this long died with its process and is not playing, whatever its
#: last recorded status says.
REPLAY_STALE_S = 15.0
PLAYING = ("running", "paused")


def replay_state(r: redis.Redis, lid: str) -> dict[str, str]:
    """The replay's state hash, with a status that tells the truth: a replay
    whose process vanished mid-match reads as "stopped", not "running"."""
    h: dict[str, str] = r.hgetall(f"replay:state:{lid}")  # type: ignore[assignment]
    if h.get("status") in PLAYING:
        beat = float(h.get("heartbeat") or 0)
        if time.time() - beat > REPLAY_STALE_S:
            h["status"] = "stopped"
    return h


def playing_replays(r: redis.Redis | None = None) -> set[str]:
    r = r or sync_client()
    return {
        lid
        for lid in r.smembers(ACTIVE_REPLAYS)  # type: ignore[union-attr]
        if replay_state(r, lid).get("status") in PLAYING
    }


@lru_cache(maxsize=1)
def sync_client() -> redis.Redis:
    return redis.Redis.from_url(settings().redis_url, decode_responses=True)


def async_client() -> aioredis.Redis:
    return aioredis.Redis.from_url(settings().redis_url, decode_responses=True)


def shard_of(match_id: str) -> int:
    return zlib.crc32(match_id.encode("utf-8")) % SHARDS


def shard_stream(shard: int) -> str:
    return f"ingest:{shard}"


def stream_for(match_id: str) -> str:
    return shard_stream(shard_of(match_id))


ALL_SHARD_STREAMS = tuple(shard_stream(i) for i in range(SHARDS))


def ensure_group(r: redis.Redis, stream: str, group: str = INGEST_GROUP) -> None:
    try:
        r.xgroup_create(stream, group, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def ensure_groups(r: redis.Redis) -> None:
    for s in ALL_SHARD_STREAMS:
        ensure_group(r, s)


def produce(kind: str, match_id: str, body: dict[str, Any], r: redis.Redis | None = None) -> str:
    """Put one piece of work on the ingest stream. `kind` is event|correction|control."""
    r = r or sync_client()
    return str(
        r.xadd(
            stream_for(match_id),
            {"kind": kind, "match": match_id, "body": json.dumps(body, separators=(",", ":"))},
            maxlen=200_000,
            approximate=True,
        )
    )


def channel(match_id: str) -> str:
    return f"match:{match_id}"


def publish(chan: str, message: dict[str, Any], r: redis.Redis | None = None) -> int:
    """Stamp a sequence number, mirror to the channel log, then publish.

    The order matters: the log write happens before the publish, so a client
    that reconnects between the two still finds the message in the log.
    """
    r = r or sync_client()
    seq = int(r.incr(f"seq:{chan}"))
    message = {**message, "seq": seq, "channel": chan}
    payload = json.dumps(message, separators=(",", ":"))
    pipe = r.pipeline(transaction=True)
    pipe.xadd(
        f"chanlog:{chan}", {"seq": seq, "msg": payload}, maxlen=CHANLOG_MAXLEN, approximate=False
    )
    pipe.publish(chan, payload)
    pipe.execute()
    return seq


async def backlog(r: aioredis.Redis, chan: str, since: int) -> list[dict[str, Any]]:
    """Everything published on `chan` after seq `since`, oldest first."""
    entries = await r.xrange(f"chanlog:{chan}", min="-", max="+")
    out = []
    for _id, fields in entries:
        if int(fields["seq"]) > since:
            out.append(json.loads(fields["msg"]))
    return out
