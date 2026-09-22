"""WebSocket gateway over a Redis pub/sub backplane.

    ingest worker ─PUBLISH match:<id>─▶ Redis ─▶ API task A ─▶ its browsers
                                             └─▶ API task B ─▶ its browsers

* One Redis connection per process, subscribed to a channel only while at
  least one local client wants it (reference counted).
* Every message carries a per-channel `seq`. A client reconnecting with
  `?since=<seq>` is first sent everything it missed from `chanlog:<channel>`,
  then joins the live stream - no gap, no duplicates. A client that sends no
  `since` starts from now: it has just fetched current state over REST, and
  replaying the channel's history at it would show old scores as new.
* Server ping every 20 s, inside the load balancer's idle timeout.
* A client whose send queue passes 100 messages is dropped: it is not keeping
  up, and one slow phone must not hold memory for everyone. It reconnects with
  `since` and loses nothing.
* No sticky sessions needed; the backplane is the point.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..streams import bus
from .metrics import METRICS

log = logging.getLogger("onside.ws")
router = APIRouter()

PING_SECONDS = 20
MAX_QUEUE = 100


class Client:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.last_seq = 0


class Manager:
    def __init__(self) -> None:
        self.clients: dict[str, set[Client]] = defaultdict(set)
        self.redis: Any = None
        self.pubsub: Any = None
        self.reader: asyncio.Task[None] | None = None
        self.lock = asyncio.Lock()

    async def start(self) -> None:
        self.redis = bus.async_client()
        self.pubsub = self.redis.pubsub()
        await self.pubsub.subscribe("__onside_keepalive__")  # pubsub needs one channel to listen
        self.reader = asyncio.create_task(self._read())

    async def stop(self) -> None:
        if self.reader:
            self.reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reader
        if self.pubsub:
            await self.pubsub.aclose()
        if self.redis:
            await self.redis.aclose()

    async def join(self, chan: str, client: Client) -> None:
        async with self.lock:
            first = not self.clients[chan]
            self.clients[chan].add(client)
            if first:
                await self.pubsub.subscribe(chan)
        METRICS.gauge("ws_clients", sum(len(v) for v in self.clients.values()))

    async def leave(self, chan: str, client: Client) -> None:
        async with self.lock:
            self.clients[chan].discard(client)
            if not self.clients[chan]:
                del self.clients[chan]
                await self.pubsub.unsubscribe(chan)
        METRICS.gauge("ws_clients", sum(len(v) for v in self.clients.values()))

    async def _read(self) -> None:
        while True:
            try:
                msg = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            except Exception:  # noqa: BLE001 - reconnect loop
                log.warning("backplane read failed; retrying")
                await asyncio.sleep(1)
                continue
            if not msg:
                continue
            chan, data = msg["channel"], msg["data"]
            for client in list(self.clients.get(chan, ())):
                if client.queue.qsize() >= MAX_QUEUE:
                    METRICS.inc("ws_slow_consumers_dropped")
                    await client.ws.close(code=4008, reason="too slow; reconnect with ?since=")
                    continue
                client.queue.put_nowait(data)
            METRICS.inc("ws_messages_fanned_out", len(self.clients.get(chan, ())))


manager = Manager()


async def _serve(ws: WebSocket, chan: str, since: int | None) -> None:
    await ws.accept()
    client = Client(ws)
    await manager.join(chan, client)
    try:
        if since is None:
            # Start from now. Joined first, so nothing published after this
            # read is lost; everything at or below it is skipped.
            since = int(await manager.redis.get(f"seq:{chan}") or 0)
            client.last_seq = since
        # Replay what the client missed, then stream. Joining *before* reading
        # the backlog, and skipping anything at or below the last replayed seq,
        # closes the gap between the two without duplicates.
        for m in await bus.backlog(manager.redis, chan, since):
            await ws.send_text(json.dumps(m))
            client.last_seq = max(client.last_seq, int(m["seq"]))
        await ws.send_text(
            json.dumps({"type": "hello", "channel": chan, "seq": client.last_seq or since})
        )

        async def pump() -> None:
            while True:
                data = await client.queue.get()
                seq = json.loads(data).get("seq", 0)
                if seq and seq <= client.last_seq:
                    continue
                client.last_seq = seq or client.last_seq
                await ws.send_text(data)

        async def ping() -> None:
            while True:
                await asyncio.sleep(PING_SECONDS)
                await ws.send_text(json.dumps({"type": "ping", "seq": client.last_seq}))

        async def drain() -> None:
            while True:
                await ws.receive_text()  # clients may send pongs; content ignored

        tasks = [asyncio.create_task(t()) for t in (pump, ping, drain)]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                raise exc
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("websocket on %s failed", chan)
    finally:
        await manager.leave(chan, client)


@router.websocket("/ws/match/{match_id}")
async def match_socket(ws: WebSocket, match_id: str, since: int | None = Query(None, ge=0)) -> None:
    await _serve(ws, bus.channel(match_id), since)


@router.websocket("/ws/feed")
async def feed_socket(ws: WebSocket, since: int | None = Query(None, ge=0)) -> None:
    """Score changes across every replay that is playing - drives the ticker."""
    await _serve(ws, "feed", since)


@router.websocket("/ws/competition/{competition_id}")
async def competition_socket(
    ws: WebSocket, competition_id: str, since: int | None = Query(None, ge=0)
) -> None:
    await _serve(ws, f"comp:{competition_id}", since)
