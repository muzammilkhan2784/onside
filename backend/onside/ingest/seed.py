"""Load the built archive into the serving stores.

    python -m onside.ingest.seed            # everything, idempotent
    python -m onside.ingest.seed --if-empty # skip when already seeded (compose)

1. Create the DynamoDB table if needed.
2. Write every match document (state, report, win probability, shots, pass
   networks) plus its listing items: competition-season, date, team fixtures,
   the news feed and story tags.
3. Derive and write the catalog: competitions and seasons, tables, teams,
   players (career numbers from DuckDB), the search index and the editorial
   collections the front page is built from.
4. Mirror the Parquet archive to object storage when the archive is on S3.
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..config import settings
from ..replay.download import BASE, CACHE, _get
from ..store import client, repo
from .catalog import competition_catalog, season_tables, team_catalog

SEED_MARKER = ("meta", "seeded")


def _load(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def load_documents(workers: int = 16) -> list[dict[str, Any]]:
    paths = sorted(settings().match_docs_dir.glob("*.json.gz"))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_load, paths))


def write_documents(docs: list[dict[str, Any]], workers: int = 8) -> None:
    chunks = [docs[i::workers] for i in range(workers)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(repo.put_documents, chunks))


def collections(cards: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Editorial collections: the front page's standing features, computed from
    the model's own numbers rather than anyone's opinion."""

    def top(items: list[dict[str, Any]], key: Any, n: int = 12) -> list[dict[str, Any]]:
        return sorted(items, key=key, reverse=True)[:n]

    knockouts = [
        c for c in cards if c["stage"] and c["stage"] not in ("Regular Season", "Group Stage")
    ]
    finals = [c for c in cards if c["stage"] == "Final"]
    return {
        "turnarounds": {
            "title": "The biggest swings",
            "blurb": "Matches where one moment moved the win probability furthest.",
            "matches": top(
                [c for c in cards if "turnaround" in c["tags"]], lambda c: c["biggestSwing"]
            ),
        },
        "finals": {
            "title": "Every final in the archive",
            "blurb": "World Cups, Euros, Champions League finals and more, newest first.",
            "matches": sorted(finals, key=lambda c: c["date"], reverse=True),
        },
        "goal_fests": {
            "title": "Goal-fests",
            "blurb": "Five goals or more.",
            "matches": top([c for c in cards if sum(c["score"]) >= 5], lambda c: sum(c["score"])),
        },
        "smash_and_grab": {
            "title": "Smash and grab",
            "blurb": "Winners who created clearly less than the side they beat.",
            "matches": top(
                [c for c in cards if "smash-and-grab" in c["tags"]],
                lambda c: abs(c["xg"][0] - c["xg"][1]),
            ),
        },
        "shootouts": {
            "title": "Settled on penalties",
            "blurb": "Knockout ties that went all the way.",
            "matches": sorted(
                [c for c in knockouts if c.get("shootout")], key=lambda c: c["date"], reverse=True
            )[:24],
        },
        "highest_xg": {
            "title": "Chance-fests",
            "blurb": "The matches with the most expected goals between the two sides.",
            "matches": top(cards, lambda c: (c["xg"][0] or 0) + (c["xg"][1] or 0)),
        },
    }


def search_index(
    comps: list[dict[str, Any]], teams: list[dict[str, Any]], players: list[dict[str, Any]]
) -> list[list[Any]]:
    """Compact rows: [kind, id, name, subtitle, weight]. The API filters these
    in memory - a few thousand short strings, far cheaper than a search service."""
    rows: list[list[Any]] = []
    for c in comps:
        rows.append(["competition", c["id"], c["name"], c["country"], 10_000 + c["matches"]])
    for t in teams:
        rows.append(
            ["team", t["id"], t["name"], ", ".join(t["competitions"][:2]), 1_000 + t["matches"]]
        )
    for p in players:
        teams_ = p.get("teams") or []
        rows.append(["player", p["id"], p["name"], teams_[0] if teams_ else "", p["matches"]])
    return rows


def mirror_archive_to_s3(only_if_missing: bool = False) -> int:
    """Copy the local Parquet archive to the object store DuckDB reads from.
    With `only_if_missing`, does nothing when the bucket already has it - so
    it is safe to run on every start, and repairs a store that lost its data."""
    s = settings()
    if not s.archive_is_s3:
        return 0
    import os

    import boto3

    local = s.data_dir / "archive" / "events"
    bucket, _, prefix = s.archive_uri[len("s3://") :].partition("/")
    s3 = boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        region_name=s.region,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "onside"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "onside-local-only"),
    )
    with contextlib.suppress(Exception):  # the bucket usually already exists
        s3.create_bucket(Bucket=bucket)
    if only_if_missing:
        have = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1).get("KeyCount", 0)
        if have:
            return 0
    files = list(local.rglob("*.parquet"))

    def up(p: Path) -> None:
        key = f"{prefix}/{p.relative_to(local).as_posix()}".lstrip("/")
        s3.upload_file(str(p), bucket, key)

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(up, files))
    return len(files)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--if-empty", action="store_true")
    args = ap.parse_args(argv)

    t0 = time.time()
    client.wait_until_ready()
    created = client.create_table()
    if args.if_empty and not created and repo.get_catalog(*SEED_MARKER):
        # DynamoDB and the object store are separate volumes; either can be
        # lost on its own. Check the archive mirror even when the table is fine.
        mirrored = mirror_archive_to_s3(only_if_missing=True)
        note = f" Restored {mirrored:,} Parquet files to the archive." if mirrored else ""
        print(f"Already seeded; nothing to do.{note}", file=sys.stderr)
        return 0

    docs = load_documents()
    if not docs:
        print(
            "No match documents found. Run `python -m onside.ingest.build` first.", file=sys.stderr
        )
        return 1
    print(f"Writing {len(docs):,} matches to DynamoDB...", file=sys.stderr, flush=True)
    write_documents(docs)
    print(f"  done in {time.time() - t0:.0f}s", file=sys.stderr, flush=True)

    cards = [repo.match_card(d) for d in docs]
    del docs

    comps_raw = _get(f"{BASE}/competitions.json", CACHE / "competitions.json")
    comps = competition_catalog(cards, comps_raw)
    repo.put_catalog("competitions", "all", comps)

    by_cs: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for c in cards:
        by_cs[(c["competition"]["id"], c["season"]["id"])].append(c)
    intl = {c["id"]: c["international"] for c in comps}
    for (cid, sid), cs_cards in by_cs.items():
        tables, note = season_tables(int(cid), intl.get(cid, False), cs_cards)
        repo.put_tables(cid, sid, tables)
        repo.put_catalog("season", f"{cid}#{sid}", {"tablesNote": note, "matches": len(cs_cards)})
    print(f"  {len(by_cs)} competition-seasons catalogued", file=sys.stderr, flush=True)

    teams = team_catalog(cards)
    repo.put_entities("team", teams)

    from ..archive import queries

    players = queries.players_catalog()
    for p in players:
        p["teams"] = list(p.get("teams") or [])
    repo.put_entities("player", players)
    print(
        f"  {len(teams):,} teams and {len(players):,} players written", file=sys.stderr, flush=True
    )

    repo.put_catalog("search", "all", search_index(comps, teams, players))
    repo.put_catalog("collections", "all", collections(cards))
    size = queries.archive_size()
    repo.put_catalog(
        "stats",
        "archive",
        {
            **size,
            "competitions": len(comps),
            "seasons": sum(len(c["seasons"]) for c in comps),
            "from": min(c["date"] for c in cards),
            "to": max(c["date"] for c in cards),
        },
    )

    mirrored = mirror_archive_to_s3()
    if mirrored:
        print(f"  mirrored {mirrored:,} Parquet files to {settings().archive_uri}", file=sys.stderr)

    repo.put_catalog(*SEED_MARKER, {"at": time.time(), "matches": len(cards)})
    print(f"Seeded {len(cards):,} matches in {time.time() - t0:.0f}s.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
