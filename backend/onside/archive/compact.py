"""The whole archive as one Parquet file, sorted by player.

The partitioned layout - a file per match - suits writing, and a many-core
laptop reads it in well under a second. A one-vCPU Lambda does not: opening
3,961 files per query costs seconds before a row is read. So the Lambda image
carries this instead (Dockerfile, target lambda): one zstd file with the
partition columns inside it and rows sorted by player, so a player's page
reads only the row groups whose min/max bracket that player's id.

    python -m onside.archive.compact <partitioned root> <out.parquet>
"""

from __future__ import annotations

import sys
import time

import duckdb

ROW_GROUP = 122_880  # DuckDB's own row-group size: pruning works per group


def compact(root: str, out: str, memory: str = "3GB") -> int:
    """Write `out` from the partitioned archive at `root`; returns the rows written."""
    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{memory}'")
    src = f"{root.rstrip('/')}/competition_id=*/season_id=*/*.parquet"
    con.execute(
        f"COPY (SELECT * FROM read_parquet('{src}', hive_partitioning = true) "
        "ORDER BY player_id NULLS LAST, match_id, idx) "
        f"TO '{out}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE {ROW_GROUP})"
    )
    row = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()
    con.close()
    return int(row[0]) if row else 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    t0 = time.time()
    n = compact(args[0], args[1])
    print(f"{n:,} events -> {args[1]} in {time.time() - t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
