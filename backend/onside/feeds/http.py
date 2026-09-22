"""Shared HTTP plumbing for the live feeds: auth header, rate limiting, retry
with backoff, and a transport seam so contract tests run against recorded
fixtures instead of the network."""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx


class RateLimiter:
    """Token bucket. football-data.org's free tier allows 10 requests a minute;
    exceeding it gets the key suspended, so the client paces itself."""

    def __init__(self, per_minute: int) -> None:
        self.capacity = per_minute
        self.tokens = float(per_minute)
        self.rate = per_minute / 60.0
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def take(self) -> None:
        with self.lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                time.sleep((1 - self.tokens) / self.rate)


class FeedError(Exception):
    """A feed refused or failed a request. `message` is written for people."""


class FeedClient:
    def __init__(
        self,
        base_url: str,
        headers: dict[str, str],
        per_minute: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.http = httpx.Client(
            base_url=base_url, headers=headers, timeout=20.0, transport=transport
        )
        self.limiter = RateLimiter(per_minute)

    def get(self, path: str, params: dict[str, Any] | None = None, attempts: int = 3) -> Any:
        delay = 2.0
        for attempt in range(attempts):
            self.limiter.take()
            try:
                resp = self.http.get(path, params=params)
            except httpx.TransportError as exc:
                if attempt == attempts - 1:
                    raise FeedError(
                        f"The feed could not be reached ({type(exc).__name__})."
                    ) from exc
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code == 429 and attempt < attempts - 1:
                time.sleep(float(resp.headers.get("Retry-After", delay)))
                delay *= 2
                continue
            if resp.status_code in (401, 403):
                raise FeedError(
                    "The feed refused the request - the API key is missing, invalid, or its "
                    "plan does not include this resource."
                )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        raise FeedError("The feed kept rate-limiting the request.")
