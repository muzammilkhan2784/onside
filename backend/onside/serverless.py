"""Onside on AWS Lambda: the free-tier deployment.

One container image, two roles. Both run behind the Lambda Web Adapter, an
extension that turns each invocation into an HTTP request to a server in the
same container:

    python -m onside.serverless api       the FastAPI app, behind CloudFront
    python -m onside.serverless worker    one job per scheduled invocation:
                                          {"job": "fixtures"}  every minute
                                          {"job": "social"}    every five

The adapter posts non-HTTP events (the schedules) to /events. Secrets come
from SSM Parameter Store - SecureString parameters under ONSIDE_SSM_PATH,
named like the environment variables they become - and are read once per
cold start, never baked into the image or the function's configuration.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any

log = logging.getLogger("onside.serverless")
PORT = int(os.environ.get("PORT", "8080"))
# Only the adapter, in the same container, talks to the server.
BIND = os.environ.get("ONSIDE_BIND", "127.0.0.1")


def load_ssm(path: str | None = None, client: Any = None) -> list[str]:
    """Copy every parameter under `path` into the environment. Returns the
    names it set - never the values."""
    path = (path if path is not None else os.environ.get("ONSIDE_SSM_PATH", "")).rstrip("/")
    if not path:
        return []
    if client is None:
        import boto3

        client = boto3.client("ssm")
    names: list[str] = []
    pages = client.get_paginator("get_parameters_by_path").paginate(
        Path=path, WithDecryption=True, Recursive=False
    )
    for page in pages:
        for p in page["Parameters"]:
            name = p["Name"].rsplit("/", 1)[-1]
            os.environ[name] = p["Value"]
            names.append(name)
    _loaded[:] = sorted(names)
    return list(_loaded)


SECRETS_EVERY_S = 900
_loaded: list[str] = []


def _names() -> list[str]:
    return list(_loaded)


def _digest(names: list[str]) -> str:
    """A fingerprint of the loaded values, to notice a rotation without
    keeping a second copy of any secret around."""
    import hashlib

    joined = "\n".join(f"{n}={os.environ.get(n, '')}" for n in sorted(names))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def worker_app() -> Any:
    """The scheduled jobs as an HTTP app, for the adapter to call."""
    from fastapi import Body, FastAPI, HTTPException

    from .config import settings
    from .feeds.football_data import FootballDataAdapter
    from .streams import bus
    from .workers import fixtures, social

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    # Kept for the life of the execution environment, so Bluesky's session is
    # refreshed from one run to the next rather than signed into every time.
    cache: dict[str, Any] = {}
    secrets = {"at": time.time(), "digest": _digest(_names())}

    def refresh_secrets() -> None:
        """Re-read Parameter Store every fifteen minutes, so a rotated key
        takes effect without a redeploy. Only a change rebuilds anything."""
        if not os.environ.get("ONSIDE_SSM_PATH") or time.time() - secrets["at"] < SECRETS_EVERY_S:
            return
        names = load_ssm()
        secrets["at"] = time.time()
        if (digest := _digest(names)) != secrets["digest"]:
            secrets["digest"] = digest
            settings.cache_clear()
            cache.clear()
            log.info("secrets changed; sources rebuilt")

    def run_fixtures() -> dict[str, Any]:
        r = bus.sync_client()
        if not settings().football_data_key:
            fixtures.publish(r, {"enabled": False, "matches": []})
            return {"enabled": False}
        # A fresh poller each run: its state lives in the store, so this is
        # right even when another environment ran the previous minute.
        body = fixtures.Poller(FootballDataAdapter(), r).tick()
        return {"ok": body["ok"], "matches": len(body["matches"])}

    def run_social() -> dict[str, Any]:
        r = bus.sync_client()
        srcs = cache.setdefault("sources", social.sources(r))
        return social.cycle(r, srcs)

    jobs = {"fixtures": run_fixtures, "social": run_social}

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/events")
    def events(event: dict[str, Any] = Body(...)) -> dict[str, Any]:  # noqa: B008
        job = jobs.get(str(event.get("job")))
        if job is None:
            raise HTTPException(400, f"unknown job {event.get('job')!r}")
        t0 = time.perf_counter()
        refresh_secrets()
        result = job()
        log.info("%s: %s in %.1fs", event["job"], result, time.perf_counter() - t0)
        return {"job": event["job"], "result": result}

    return app


def main(argv: list[str] | None = None) -> None:
    role = (argv or sys.argv[1:] or ["api"])[0]
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    loaded = load_ssm()
    if loaded:
        log.info("secrets from SSM: %s", ", ".join(loaded))

    import uvicorn

    if role == "api":
        uvicorn.run("onside.api.main:app", host=BIND, port=PORT, proxy_headers=True)
    elif role == "worker":
        uvicorn.run(worker_app(), host=BIND, port=PORT)
    else:
        raise SystemExit(f"unknown role {role!r}: expected api or worker")


if __name__ == "__main__":
    main()
