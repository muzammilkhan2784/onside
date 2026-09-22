"""Build the archive: every match StatsBomb publishes, end to end.

For each match this downloads the events and lineups, normalises them into the
canonical model, writes the events to the Parquet archive, and writes the
derived match document (state, win probability, report, shots, pass networks,
metrics) to `data/processed/matches/<id>.json.gz`. `seed.py` then loads those
documents into DynamoDB.

Resumable and idempotent: a match whose document already exists is skipped
unless `--force` is given, so an interrupted run picks up where it stopped.

    python -m onside.ingest.build                # everything
    python -m onside.ingest.build --limit 50     # a quick sample
    python -m onside.ingest.build --competition 43
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from ..archive.writer import write_match
from ..config import settings
from ..feeds.statsbomb import normalise_match
from ..models.features import Elo
from ..replay.download import BASE, CACHE, _get
from .document import build_document

USER_AGENT = "onside/0.1 (+portfolio project; StatsBomb open data)"


def _fetch_json(url: str, attempts: int = 4) -> Any:
    """GET with retry and backoff. raw.githubusercontent.com rate-limits bursts."""
    delay = 1.0
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if attempt == attempts - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == attempts - 1:
                raise
        time.sleep(delay)
        delay *= 2
    return None


def match_index() -> list[dict[str, Any]]:
    """Every match in the open-data set, annotated with its competition, in
    global date order."""
    comps = _get(f"{BASE}/competitions.json", CACHE / "competitions.json")
    out: list[dict[str, Any]] = []
    for cs in comps:
        cid, sid = cs["competition_id"], cs["season_id"]
        try:
            matches = _get(
                f"{BASE}/matches/{cid}/{sid}.json", CACHE / "matches" / f"{cid}_{sid}.json"
            )
        except urllib.error.HTTPError:
            continue
        for m in matches:
            m["_competition_id"] = cid
            m["_competition_name"] = cs["competition_name"]
            m["_competition_gender"] = cs.get("competition_gender", "")
            m["_competition_international"] = cs.get("competition_international", False)
            m["_country"] = cs.get("country_name", "")
            m["_season_id"] = sid
            m["_season_name"] = cs["season_name"]
            out.append(m)
    out.sort(key=lambda m: (m.get("match_date", ""), m.get("kick_off") or "", m["match_id"]))
    return out


def causal_elo(index: list[dict[str, Any]]) -> dict[int, float]:
    """Elo difference for every match, read strictly before that match updates it."""
    pools: dict[int, Elo] = {}
    out: dict[int, float] = {}
    for m in index:
        elo = pools.setdefault(m["_competition_id"], Elo())
        h = str(m["home_team"]["home_team_id"])
        a = str(m["away_team"]["away_team_id"])
        out[m["match_id"]] = elo.diff(h, a)
        elo.update(h, a, m.get("home_score") or 0, m.get("away_score") or 0)
    return out


def doc_path(match_id: int) -> Path:
    return settings().match_docs_dir / f"{match_id}.json.gz"


def process_match(meta: dict[str, Any], elo_diff: float, archive_root: str) -> dict[str, Any]:
    """Runs in a worker process. Returns a small summary for the index."""
    mid = int(meta["match_id"])
    raw = _fetch_json(f"{BASE}/events/{mid}.json")
    if not raw:
        return {"id": mid, "skipped": "no event data"}
    lineups_path = CACHE / "lineups" / f"{mid}.json"
    try:
        lineups = _get(f"{BASE}/lineups/{mid}.json", lineups_path)
    except urllib.error.HTTPError:
        lineups = []
    nicknames = {
        str(p["player_id"]): p["player_nickname"]
        for team in lineups
        for p in team.get("lineup", [])
        if p.get("player_nickname")
    }
    events = normalise_match(raw, str(mid), nicknames)
    write_match(
        Path(archive_root),
        events,
        competition_id=int(meta["_competition_id"]),
        season_id=int(meta["_season_id"]),
        match_id=mid,
        match_date=meta.get("match_date", ""),
    )
    doc = build_document(events, meta, raw_lineups=lineups, elo_diff=elo_diff)
    path = doc_path(mid)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))
    tmp.replace(path)
    return {"id": mid, "events": doc["eventCount"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--competition", type=int, default=0)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    s = settings()
    archive_root = s.archive_uri if not s.archive_is_s3 else str(s.data_dir / "archive" / "events")
    index = match_index()
    elo = causal_elo(index)
    todo = [m for m in index if not args.competition or m["_competition_id"] == args.competition]
    if args.limit:
        todo = todo[: args.limit]
    if not args.force:
        todo = [m for m in todo if not doc_path(m["match_id"]).exists()]

    total = len(index)
    print(
        f"{total:,} matches in the open-data set; {len(todo):,} to build "
        f"with {args.workers} workers.",
        file=sys.stderr,
        flush=True,
    )
    t0 = time.time()
    done = failed = skipped = 0
    events_total = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(process_match, m, elo[m["match_id"]], archive_root): m for m in todo}
        for fut in as_completed(futs):
            m = futs[fut]
            try:
                res = fut.result()
                if "skipped" in res:
                    skipped += 1
                else:
                    done += 1
                    events_total += res["events"]
            except Exception as exc:  # one bad match never stops the archive
                failed += 1
                print(f"  failed {m['match_id']}: {type(exc).__name__}: {exc}", file=sys.stderr)
            n = done + failed + skipped
            if n % 100 == 0 or n == len(todo):
                rate = n / max(time.time() - t0, 1e-6)
                left = (len(todo) - n) / rate if rate else 0
                print(
                    f"  {n:,} of {len(todo):,} built, {events_total:,} events so far, "
                    f"about {left / 60:.0f} min left",
                    file=sys.stderr,
                    flush=True,
                )

    print(
        f"Built {done:,} matches ({events_total:,} events) in {(time.time() - t0) / 60:.1f} min; "
        f"{skipped} had no event data, {failed} failed.",
        file=sys.stderr,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
