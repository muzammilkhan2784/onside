"""Minimal Prometheus exposition, no dependency.

Request counts and latency histograms by route template, plus the WebSocket
gauges. Route templates, not raw paths, so `/api/matches/{match_id}` is one
series rather than one per match.
"""

from __future__ import annotations

import threading
from collections import defaultdict

BUCKETS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000)


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self.latency: dict[str, list[int]] = defaultdict(lambda: [0] * (len(BUCKETS) + 1))
        self.latency_sum: dict[str, float] = defaultdict(float)
        self.gauges: dict[str, float] = defaultdict(float)
        self.counters: dict[str, int] = defaultdict(int)

    def observe(self, method: str, route: str, status: int, ms: float) -> None:
        with self._lock:
            self.requests[(method, route, status)] += 1
            b = self.latency[route]
            for i, edge in enumerate(BUCKETS):
                if ms <= edge:
                    b[i] += 1
                    break
            else:
                b[-1] += 1
            self.latency_sum[route] += ms

    def gauge(self, name: str, value: float) -> None:
        with self._lock:
            self.gauges[name] = value

    def inc(self, name: str, by: int = 1) -> None:
        with self._lock:
            self.counters[name] += by

    def render(self) -> str:
        out = ["# TYPE onside_http_requests_total counter"]
        with self._lock:
            for (m, r, s), n in sorted(self.requests.items()):
                out.append(
                    f'onside_http_requests_total{{method="{m}",route="{r}",status="{s}"}} {n}'
                )
            out.append("# TYPE onside_http_request_ms histogram")
            for route, b in sorted(self.latency.items()):
                cum = 0
                for i, edge in enumerate(BUCKETS):
                    cum += b[i]
                    out.append(
                        f'onside_http_request_ms_bucket{{route="{route}",le="{edge}"}} {cum}'
                    )
                cum += b[-1]
                out.append(f'onside_http_request_ms_bucket{{route="{route}",le="+Inf"}} {cum}')
                out.append(
                    f'onside_http_request_ms_sum{{route="{route}"}} {self.latency_sum[route]:.1f}'
                )
                out.append(f'onside_http_request_ms_count{{route="{route}"}} {cum}')
            for name, v in sorted(self.gauges.items()):
                out.append(f"# TYPE onside_{name} gauge\nonside_{name} {v}")
            for name, v in sorted(self.counters.items()):
                out.append(f"# TYPE onside_{name}_total counter\nonside_{name}_total {v}")
        return "\n".join(out) + "\n"


METRICS = Metrics()
