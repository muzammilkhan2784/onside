"""Replay control, health and metrics."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from ...store import client as store_client
from ...store import repo
from ...streams import bus
from ..errors import ApiError, not_found
from ..metrics import METRICS
from ..schemas import ReplayCommand, ReplayRequest, ReplayStatus


def _realtime_only() -> None:
    """Replays run on Redis Streams and long-running workers. The free-tier
    deployment has neither, and says so rather than failing obscurely."""
    if not store_client.settings().realtime:
        raise ApiError(
            503,
            "replays_unavailable",
            "Replays need the full deployment - Redis Streams and always-on workers - and "
            "this one is the free-tier version, which serves the archive, current football "
            "and the social feed. Run Onside with docker compose to watch replays.",
            {"feature": "replays"},
        )


replay = APIRouter(prefix="/api/replay", tags=["replay"], dependencies=[Depends(_realtime_only)])
ops = APIRouter(tags=["ops"])


@replay.post(
    "/start",
    response_model=ReplayStatus,
    status_code=202,
    summary="Replay any archived match as if it were live",
)
def start(req: ReplayRequest) -> dict[str, Any]:
    """Queues the replay; the replay service picks it up within a few seconds.
    The replay runs under the id `live-<match_id>` and never changes the
    archived match."""
    if repo.get_card(str(req.match_id)) is None:
        raise not_found("match", str(req.match_id), "Pick any id from /api/feed.")
    bus.sync_client().xadd(
        bus.REPLAY_CONTROL_STREAM,
        {
            "command": "start",
            "match": str(req.match_id),
            "speed": str(req.speed),
            "inject_var": "1" if req.inject_var else "0",
        },
    )
    return {
        "matchId": f"live-{req.match_id}",
        "of": str(req.match_id),
        "status": "queued",
        "speed": req.speed,
    }


def _command(cmd: ReplayCommand, command: str) -> dict[str, Any]:
    r = bus.sync_client()
    key = f"replay:state:{cmd.match_id}"
    if not r.exists(key):
        raise not_found("replay", cmd.match_id, "GET /api/replay/status lists running replays.")
    fields = {"command": command}
    if cmd.speed:
        fields["speed"] = str(cmd.speed)
    r.hset(key, mapping=fields)
    return _status(cmd.match_id)


@replay.post("/pause", response_model=ReplayStatus)
def pause(cmd: ReplayCommand) -> dict[str, Any]:
    return _command(cmd, "pause")


@replay.post("/resume", response_model=ReplayStatus)
def resume(cmd: ReplayCommand) -> dict[str, Any]:
    return _command(cmd, "")


@replay.post("/stop", response_model=ReplayStatus)
def stop(cmd: ReplayCommand) -> dict[str, Any]:
    return _command(cmd, "stop")


@replay.post("/speed", response_model=ReplayStatus)
def speed(cmd: ReplayCommand) -> dict[str, Any]:
    if not cmd.speed:
        raise ApiError(
            400, "speed_required", "Send a speed between 1 and 600 match-seconds per second."
        )
    r = bus.sync_client()
    r.hset(f"replay:state:{cmd.match_id}", "speed", str(cmd.speed))
    return _status(cmd.match_id)


def _status(lid: str) -> dict[str, Any]:
    h = bus.replay_state(bus.sync_client(), lid)
    return {
        "matchId": lid,
        "of": h.get("of", ""),
        "title": h.get("title", ""),
        "status": h.get("status", "unknown"),
        "speed": float(h.get("speed", 0) or 0),
        "sent": int(h.get("sent", 0) or 0),
        "total": int(h.get("total", 0) or 0),
        "minute": int(h.get("minute", 0) or 0),
    }


@replay.get("/status", response_model=list[ReplayStatus], summary="Every replay and where it is")
def status() -> list[dict[str, Any]]:
    """Playing replays first, then finished and stopped ones, so
    a replay you just watched to full time can still be opened."""
    r = bus.sync_client()
    rows = [_status(lid) for lid in r.smembers(bus.ACTIVE_REPLAYS)]  # type: ignore[union-attr]
    return sorted(rows, key=lambda x: (x["status"] not in bus.PLAYING, x["title"]))


@ops.get("/health", summary="Liveness and dependency checks")
def health() -> dict[str, Any]:
    checks: dict[str, str] = {}
    t0 = time.perf_counter()
    store = "redis" if store_client.settings().realtime else "kv"
    try:
        bus.sync_client().ping()
        checks[store] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks[store] = f"unavailable: {type(exc).__name__}"
    try:
        store_client.resource().meta.client.describe_table(TableName=store_client.settings().table)
        checks["dynamodb"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["dynamodb"] = f"unavailable: {type(exc).__name__}"
    ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ok" if ok else "degraded",
        "checks": checks,
        "ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def _fixtures_on() -> bool:
    """Whether the fixtures worker is running with a key - from what it last
    stored, since the API itself is never given the feed's key."""
    import json

    from ...workers import fixtures

    try:
        raw = bus.sync_client().get(fixtures.KEY)
    except Exception:  # noqa: BLE001 - a store hiccup is not a reason to fail this
        return False
    return bool(raw) and bool(json.loads(raw).get("enabled"))


@ops.get("/api/features", summary="What this deployment can do")
def features() -> dict[str, Any]:
    """The web app asks once and shows only what works here: the free-tier
    deployment has no replays and no WebSockets; everything else is the same."""
    s = store_client.settings()
    return {
        "realtime": s.realtime,
        "replays": s.realtime,
        "current": _fixtures_on(),
        "deployment": "full" if s.realtime else "free-tier",
    }


@ops.get("/metrics", response_class=PlainTextResponse, summary="Prometheus metrics")
def metrics() -> str:
    return METRICS.render()
