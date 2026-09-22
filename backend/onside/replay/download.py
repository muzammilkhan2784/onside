"""Fetch StatsBomb open data and cache it on disk.

StatsBomb's open data is free to use; published analysis must credit StatsBomb.
See ATTRIBUTION.md. Nothing here scrapes anything: these are the published
raw.githubusercontent.com paths of the open-data repository.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..config import settings

BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
#: Raw StatsBomb JSON cache. Lives under the configured data directory so the
#: same code works from a checkout and from the installed package in a container.
CACHE = settings().data_dir / "raw"

# Competition/season ids in the StatsBomb open-data set.
WORLD_CUP_2022 = (43, 106)
EURO_2024 = (55, 282)


def _get(url: str, dest: Path) -> Any:
    """Download `url` to `dest` unless already cached, then parse it."""
    if dest.exists() and dest.stat().st_size > 0:
        return json.loads(dest.read_text(encoding="utf-8"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "onside/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = resp.read()
    dest.write_bytes(payload)
    return json.loads(payload.decode("utf-8"))


def fetch_matches(competition_id: int, season_id: int) -> list[dict[str, Any]]:
    """Match metadata for one competition-season."""
    return _get(
        f"{BASE}/matches/{competition_id}/{season_id}.json",
        CACHE / "matches" / f"{competition_id}_{season_id}.json",
    )


def fetch_events(match_id: int) -> list[dict[str, Any]]:
    """The full raw event log for one match."""
    return _get(f"{BASE}/events/{match_id}.json", CACHE / "events" / f"{match_id}.json")


def fetch_lineups(match_id: int) -> list[dict[str, Any]]:
    return _get(f"{BASE}/lineups/{match_id}.json", CACHE / "lineups" / f"{match_id}.json")


def fetch_competition_season(
    competition_id: int, season_id: int, workers: int = 8
) -> list[dict[str, Any]]:
    """Download every match in a competition-season. Idempotent and resumable."""
    matches = fetch_matches(competition_id, season_id)
    ids = [m["match_id"] for m in matches]
    done = 0

    def one(mid: int) -> int:
        nonlocal done
        try:
            fetch_events(mid)
        except urllib.error.HTTPError as exc:  # a few open-data matches lack events
            print(f"  skipped {mid}: {exc.code}", file=sys.stderr)
        done += 1
        if done % 8 == 0 or done == len(ids):
            print(f"  {done}/{len(ids)} matches cached", file=sys.stderr)
        return mid

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, ids))
    return matches


def nickname_map(match_id: int) -> dict[str, str]:
    """Player id -> the name a broadcaster would say, where one is recorded."""
    out: dict[str, str] = {}
    try:
        for team in fetch_lineups(match_id):
            for p in team.get("lineup", []):
                nick = p.get("player_nickname")
                if nick:
                    out[str(p["player_id"])] = nick
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return {}  # names stay long rather than the export failing
    return out


if __name__ == "__main__":
    comp, season = WORLD_CUP_2022
    if len(sys.argv) == 3:
        comp, season = int(sys.argv[1]), int(sys.argv[2])
    print(f"Downloading competition {comp}, season {season} into {CACHE}", file=sys.stderr)
    ms = fetch_competition_season(comp, season)
    print(f"Done: {len(ms)} matches.", file=sys.stderr)
