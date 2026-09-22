"""Build the win-probability training set across the whole open-data archive.

Downloads every match StatsBomb publishes, reduces each one to per-minute
feature rows, and caches the reduced form. Raw event JSON is ~3MB a match and
there are thousands of them, so raw files are discarded after extraction
unless the match is on `KEEP_RAW` (the demo match, and anything the tests
read).

Two things here are load-bearing and easy to get silently wrong:

* **Elo is causal and per-competition.** Ratings pool within a competition,
  because La Liga teams never play NWSL teams, and a rating is only ever read
  *before* the match that updates it.
* **The split is by date, not by row and not by competition.** Training on
  earlier seasons and testing on later ones is the honest split, and it keeps
  Elo warm on both sides - an earlier version split by competition, which left
  every test team on the default rating and produced a model worse than
  "whoever is ahead wins".
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any

import numpy as np

from ..config import settings
from ..feeds.statsbomb import normalise_match
from ..replay.download import BASE, CACHE, _get
from .features import FEATURE_NAMES, Elo, match_minute_rows

DATASET = settings().processed_dir / "wp_rows.npz"

#: Matches whose raw JSON is kept on disk after extraction.
KEEP_RAW = {3869685}  # the 2022 World Cup final - the demo match

_print_lock = Lock()


def all_competition_seasons() -> list[dict[str, Any]]:
    return _get(f"{BASE}/competitions.json", CACHE / "competitions.json")


def _match_index() -> list[dict[str, Any]]:
    """Every match in the open-data set, with its competition and date."""
    out: list[dict[str, Any]] = []
    for cs in all_competition_seasons():
        cid, sid = cs["competition_id"], cs["season_id"]
        try:
            matches = _get(
                f"{BASE}/matches/{cid}/{sid}.json",
                CACHE / "matches" / f"{cid}_{sid}.json",
            )
        except urllib.error.HTTPError:
            continue
        for m in matches:
            m["_competition_id"] = cid
            m["_season_id"] = sid
            m["_competition_name"] = cs["competition_name"]
            m["_season_name"] = cs["season_name"]
            out.append(m)
    # Global date order. Elo depends on this being right.
    out.sort(key=lambda m: (m.get("match_date", ""), m.get("kick_off") or "", m["match_id"]))
    return out


def _events_for(match_id: int) -> list[dict[str, Any]] | None:
    path = CACHE / "events" / f"{match_id}.json"
    if path.exists() and path.stat().st_size > 0:
        return json.loads(path.read_text(encoding="utf-8"))
    url = f"{BASE}/events/{match_id}.json"
    req = urllib.request.Request(url, headers={"User-Agent": "onside/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None
    if match_id in KEEP_RAW:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return json.loads(payload.decode("utf-8"))


def build(limit: int | None = None, workers: int = 12) -> dict[str, np.ndarray]:
    """Download, reduce and cache. Prints progress in plain English."""
    index = _match_index()
    if limit:
        index = index[:limit]
    print(f"{len(index)} matches in the open-data set.", file=sys.stderr, flush=True)

    elos: dict[int, Elo] = {}
    X: list[tuple[float, ...]] = []
    y: list[int] = []
    dates: list[str] = []
    comps: list[int] = []
    match_ids: list[int] = []
    done = 0
    with_events = 0

    # Fetch in parallel but process in date-ordered chunks: a parsed match is
    # tens of MB in Python objects, so holding the whole archive in memory at
    # once is not an option. Chunks stay in date order, which is what Elo
    # causality depends on.
    chunk_size = max(workers * 4, 32)
    for start in range(0, len(index), chunk_size):
        chunk = index[start : start + chunk_size]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            raws = list(pool.map(lambda m: _events_for(m["match_id"]), chunk))

        for m, raw in zip(chunk, raws, strict=True):
            done += 1
            if not raw:
                continue
            with_events += 1
            mid = m["match_id"]
            cid = m["_competition_id"]
            elo = elos.setdefault(cid, Elo())
            home_id = str(m["home_team"]["home_team_id"])
            away_id = str(m["away_team"]["away_team_id"])
            try:
                events = normalise_match(raw, str(mid))
                rows = match_minute_rows(
                    events,
                    home_id=home_id,
                    away_id=away_id,
                    match_id=str(mid),
                    elo_diff=elo.diff(home_id, away_id),  # read strictly before update
                    is_neutral_venue=cid in (43, 55, 72, 223, 1267, 53, 1470),
                )
            except Exception as exc:  # one bad match must not kill the build
                print(f"  skipped {mid}: {exc}", file=sys.stderr)
                continue
            for r in rows:
                X.append(r.features)
                y.append(r.label)
                dates.append(m.get("match_date", ""))
                comps.append(cid)
                match_ids.append(mid)
            elo.update(home_id, away_id, m.get("home_score", 0), m.get("away_score", 0))

        del raws
        print(
            f"  {done}/{len(index)} matches processed, {len(X):,} rows",
            file=sys.stderr,
            flush=True,
        )

    print(f"{with_events} matches had event data.", file=sys.stderr, flush=True)

    data = {
        "X": np.asarray(X, dtype=np.float32),
        "y": np.asarray(y, dtype=np.int8),
        "date": np.asarray(dates),
        "competition": np.asarray(comps, dtype=np.int32),
        "match_id": np.asarray(match_ids, dtype=np.int64),
        "feature_names": np.asarray(FEATURE_NAMES),
    }
    DATASET.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(DATASET, **data)
    print(
        f"Wrote {data['X'].shape[0]:,} rows from {len(set(match_ids)):,} matches to {DATASET}",
        file=sys.stderr,
    )
    return data


def load() -> dict[str, np.ndarray]:
    if not DATASET.exists():
        raise FileNotFoundError(
            f"No dataset at {DATASET}. Run `python -m onside.models.dataset` first."
        )
    with np.load(DATASET, allow_pickle=False) as f:
        return {k: f[k] for k in f.files}


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    build(limit=lim)
