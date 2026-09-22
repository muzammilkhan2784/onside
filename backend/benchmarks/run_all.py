"""Measure the claims the README makes.

    python -m benchmarks.run_all            # everything
    python -m benchmarks.run_all ingest     # one section

Run it against an isolated instance, so a running stack cannot compete with it
for the same streams and the same projections:

    ONSIDE_TABLE=onside_bench ONSIDE_REDIS_URL=redis://localhost:6379/9         python -m benchmarks.run_all

Results are written to benchmarks/results/*.json and rendered into
benchmarks/results/SUMMARY.md. Every number here is measured on the machine
that runs it; the README says which machine produced the committed set.

Sections
  ingest      replay a match through the real pipeline: events/second, and the
              latency from a feed event being produced to the browser diff
  correction  what a VAR overturn costs end to end
  analytics   DuckDB over Parquet vs reading the same events out of DynamoDB
  page        the weight of the low-bandwidth match page
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from typing import Any

from onside.config import ROOT, settings
from onside.store import client as store_client
from onside.store import codec, repo
from onside.streams import bus

RESULTS = ROOT / "benchmarks" / "results"
DEMO = 3869685


def _pct(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    values = sorted(values)
    return {
        "p50": round(statistics.median(values), 1),
        "p95": round(values[min(len(values) - 1, int(len(values) * 0.95))], 1),
        "p99": round(values[min(len(values) - 1, int(len(values) * 0.99))], 1),
        "max": round(values[-1], 1),
    }


# ---------------------------------------------------------------------------
# ingest: the whole pipeline at speed
# ---------------------------------------------------------------------------

def bench_ingest(match_id: int = DEMO, chunk: int = 200) -> dict[str, Any]:
    """Push a real match through the pipeline and split the time by where it goes.

    A single throughput number would hide the interesting part: nearly all of
    it is the durable append, and on a laptop that is DynamoDB Local - a Java
    emulator in Docker that writes roughly 200 items a second. The projection
    (fold, features, model, metrics, report, shot map) is measured separately,
    because that is the part this project actually wrote.
    """
    import dataclasses

    from onside.feeds.statsbomb import normalise_match
    from onside.ingest.build import causal_elo, match_index
    from onside.replay.download import fetch_events, fetch_lineups
    from onside.workers.projector import project_log

    # Prefixed "live-" so the replay-only delete guard accepts it, and suffixed
    # so it can never collide with a replay someone is watching.
    lid = f"live-bench-{match_id}"
    r = bus.sync_client()
    index = match_index()
    meta = {**next(m for m in index if m["match_id"] == match_id), "match_id": lid,
            "_elo_diff": causal_elo(index)[match_id], "_replay": {}}
    r.set(f"live:meta:{lid}", json.dumps(meta))
    r.set(f"live:lineups:{lid}", json.dumps(fetch_lineups(match_id)))
    events = [dataclasses.replace(e, match_id=lid)
              for e in normalise_match(fetch_events(match_id), lid)]

    stream = bus.stream_for(lid)
    r.delete(stream, f"chanlog:{bus.channel(lid)}", f"seq:{bus.channel(lid)}")
    repo.clear_log(lid)
    repo.delete_match(lid)
    bus.ensure_group(r, stream)

    produce_ms: list[float] = []
    decode_ms: list[float] = []
    append_ms: list[float] = []
    project_ms: list[float] = []
    log: list[Any] = []
    before: dict[str, Any] | None = None
    t0 = time.perf_counter()

    for i in range(0, len(events), chunk):
        batch = events[i:i + chunk]

        t = time.perf_counter()
        for e in batch:
            bus.produce("event", lid, codec.event_to_dict(e), r)
        produce_ms.append((time.perf_counter() - t) * 1000)

        t = time.perf_counter()
        resp = r.xreadgroup(bus.INGEST_GROUP, "bench", {stream: ">"}, count=5000)
        msgs = resp[0][1] if resp else []
        decoded = [codec.event_from_dict(json.loads(f["body"])) for _, f in msgs]
        decode_ms.append((time.perf_counter() - t) * 1000)

        t = time.perf_counter()
        repo.append_batch(decoded, [])
        append_ms.append((time.perf_counter() - t) * 1000)

        log.extend(decoded)
        t = time.perf_counter()
        before = project_log(lid, log, [], before=before, r=r)
        project_ms.append((time.perf_counter() - t) * 1000)

        if msgs:
            r.xack(stream, bus.INGEST_GROUP, *[m for m, _ in msgs])

    elapsed = time.perf_counter() - t0
    published = len(r.xrange(f"chanlog:{bus.channel(lid)}"))
    doc = repo.get_document(lid)
    r.delete(stream, f"chanlog:{bus.channel(lid)}", f"seq:{bus.channel(lid)}",
             f"live:meta:{lid}", f"live:lineups:{lid}")
    repo.clear_log(lid)
    repo.delete_match(lid)

    total_project = sum(project_ms)
    return {
        "match": f"{meta['home_team']['home_team_name']} v {meta['away_team']['away_team_name']}",
        "events": len(events),
        "batch_size": chunk,
        "batches": len(project_ms),
        "wall_seconds": round(elapsed, 2),
        "events_per_second_end_to_end": round(len(events) / elapsed),
        "events_per_second_projection_only": round(len(events) / (total_project / 1000)),
        "per_batch_ms": {
            "produce_to_stream": _pct(produce_ms),
            "read_and_decode": _pct(decode_ms),
            "append_to_dynamodb": _pct(append_ms),
            "project_and_publish": _pct(project_ms),
        },
        "share_of_time": {
            "append_to_dynamodb": f"{sum(append_ms) / (elapsed * 1000):.0%}",
            "project_and_publish": f"{total_project / (elapsed * 1000):.0%}",
            "stream_io": f"{(sum(produce_ms) + sum(decode_ms)) / (elapsed * 1000):.0%}",
        },
        "messages_published": published,
        "final_score": doc["score"] if doc else None,
        "note": "One worker, one match, on a laptop against DynamoDB Local in Docker. "
                "Managed DynamoDB writes an order of magnitude faster; the projection "
                "figure is independent of the store. The pipeline shards by match, so "
                "throughput across matches scales with workers.",
    }


# ---------------------------------------------------------------------------
# correction: what a VAR overturn costs
# ---------------------------------------------------------------------------

def bench_correction(match_id: int = DEMO, repeats: int = 15) -> dict[str, Any]:
    from onside.domain.match_state import project
    from onside.domain.narrative.writer import write
    from onside.feeds.statsbomb import normalise_match
    from onside.ingest.build import match_index
    from onside.ingest.document import build_document
    from onside.models.predict import series_for_match
    from onside.replay.download import fetch_events
    from onside.replay.var_injector import inject

    events = normalise_match(fetch_events(match_id), str(match_id))
    meta = next(m for m in match_index() if m["match_id"] == match_id)
    corrections = inject(events, match_id=str(match_id), disallow=1, amend=1)
    log = [*events, *corrections]
    state = project(log)
    home, away = state.home.id, state.away.id

    def timed(fn: Any) -> dict[str, float]:
        fn()
        return _pct([(lambda t0: (fn(), (time.perf_counter() - t0) * 1000)[1])(time.perf_counter())
                     for _ in range(repeats)])

    series = series_for_match(events, home_id=home, away_id=away, match_id=str(match_id))
    out = {
        "match": f"{state.home.name} v {state.away.name}",
        "events": len(events),
        "rebuild_state_ms": timed(lambda: project(log)),
        "recompute_win_probability_ms": timed(
            lambda: series_for_match(events, home_id=home, away_id=away, match_id=str(match_id))),
        "regenerate_report_ms": timed(lambda: write(state, events, series)),
        "rebuild_whole_document_ms": timed(
            lambda: build_document(events, meta, corrections=corrections, live=True)),
    }
    out["full_propagation_p95_ms"] = round(out["rebuild_whole_document_ms"]["p95"], 1)
    out["note"] = ("A correction rebuilds the document from the log rather than patching state: "
                   "state, features, model, metrics, report and shot map together.")
    return out


# ---------------------------------------------------------------------------
# analytics: the reason storage is split by workload
# ---------------------------------------------------------------------------

def bench_analytics(sample_matches: int = 10) -> dict[str, Any]:
    """"Every shot from outside the box, by player" over a competition.

    DuckDB answers it from the Parquet archive. DynamoDB would have to read
    every event item for those matches: the sample below is measured, and the
    full-competition figure is a projection from it, marked as such.
    """
    from onside.archive import queries
    from onside.archive.duck import query as duck_query
    from onside.feeds.statsbomb import normalise_match
    from onside.replay.download import fetch_events

    t0 = time.perf_counter()
    rows = queries.shots(competition_id=11, outside_box=True, limit=5000)
    duck_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    totals = duck_query(
        "SELECT count(*) AS events, count(DISTINCT match_id) AS matches FROM events WHERE competition_id = 11")
    scan_ms = (time.perf_counter() - t0) * 1000
    la_liga_events = int(totals[0]["events"])
    la_liga_matches = int(totals[0]["matches"])

    # DynamoDB: load a sample of matches' events, then read them back the way a
    # query would have to.
    bench_ids = [m["match_id"] for m in _la_liga_sample(sample_matches)]
    loaded = 0
    for mid in bench_ids:
        events = normalise_match(fetch_events(mid), f"live-bench-{mid}")
        repo.append_batch(events, [])
        loaded += len(events)
    t0 = time.perf_counter()
    read = sum(len(repo.read_log(f"live-bench-{mid}")[0]) for mid in bench_ids)
    dynamo_ms = (time.perf_counter() - t0) * 1000
    for mid in bench_ids:
        repo.clear_log(f"live-bench-{mid}")

    per_event_ms = dynamo_ms / max(read, 1)
    projected = per_event_ms * la_liga_events
    return {
        "question": "Every shot from outside the box in La Liga, grouped by player",
        "archive": {"competition": "La Liga", "matches": la_liga_matches, "events": la_liga_events},
        "duckdb_ms": round(duck_ms, 1),
        "duckdb_rows": len(rows),
        "duckdb_full_scan_ms": round(scan_ms, 1),
        "dynamodb_sample": {"matches": len(bench_ids), "events": read, "ms": round(dynamo_ms, 1)},
        "dynamodb_projected_ms": round(projected, 1),
        "speedup": round(projected / max(duck_ms, 0.001)),
        "note": "The DynamoDB figure is measured over a sample and projected to the full "
                "competition, because storing 1.8M event items to answer one analytical "
                "question is the thing the split architecture exists to avoid. "
                "DynamoDB Local runs in Docker here; managed DynamoDB is faster per request "
                "but the shape of the result does not change.",
    }


def _la_liga_sample(n: int) -> list[dict[str, Any]]:
    from onside.ingest.build import match_index

    return [m for m in match_index() if m["_competition_id"] == 11][:n]


# ---------------------------------------------------------------------------
# page weight
# ---------------------------------------------------------------------------

def bench_page() -> dict[str, Any]:
    from fastapi.testclient import TestClient

    from onside.api.main import create_app

    with TestClient(create_app()) as c:
        lite = c.get(f"/m/{DEMO}")
        api = c.get(f"/api/matches/{DEMO}")
    return {
        "lite_page_bytes": len(lite.content),
        "lite_page_kb": round(len(lite.content) / 1024, 1),
        "match_state_json_kb": round(len(api.content) / 1024, 1),
        "javascript_required": False,
        "note": "The no-JavaScript match page at /m/<id>, gzip off. The interactive app "
                "progressively enhances from the same data.",
    }


SECTIONS = {"ingest": bench_ingest, "correction": bench_correction,
            "analytics": bench_analytics, "page": bench_page}


def render(results: dict[str, Any]) -> str:
    lines = ["# Benchmarks", "",
             f"Measured {time.strftime('%Y-%m-%d')} on the machine named in the README.", ""]
    for name, data in results.items():
        lines += [f"## {name}", "", "```json", json.dumps(data, indent=2), "```", ""]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    wanted = [a for a in argv if a in SECTIONS] or list(SECTIONS)
    if settings().table == "onside":
        print("Warning: benchmarking against the main table and Redis database. A running "
              "stack will compete for the same shards. See the module docstring.", file=sys.stderr)
    store_client.create_table()
    RESULTS.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    for name in wanted:
        print(f"== {name}", file=sys.stderr, flush=True)
        results[name] = SECTIONS[name]()
        (RESULTS / f"{name}.json").write_text(json.dumps(results[name], indent=2), encoding="utf-8")
        print(json.dumps(results[name], indent=2)[:900], file=sys.stderr)
    existing = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                for p in RESULTS.glob("*.json") if p.stem != "SUMMARY"}
    (RESULTS / "SUMMARY.md").write_text(render(existing), encoding="utf-8")
    print(f"\nWrote {RESULTS / 'SUMMARY.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
