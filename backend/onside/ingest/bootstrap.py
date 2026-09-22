"""First-run bootstrap for `docker compose up`.

On a clean clone there is no archive yet. Building all 3,961 matches downloads
about 12 GB and takes several minutes, which is the wrong first impression. So
by default the bootstrap builds two tournaments - the 2022 World Cup and Euro
2024, 115 matches - which is enough for every page to work and for the final
to replay, then seeds. Set ONSIDE_BOOTSTRAP=full to build the whole archive.

Idempotent: with documents already built and the table already seeded, it does
nothing and exits in a second.
"""

from __future__ import annotations

import os
import sys

from ..config import settings
from . import build, seed

QUICK = (43, 55)  # FIFA World Cup, UEFA Euro


def main() -> int:
    docs = list(settings().match_docs_dir.glob("*.json.gz"))
    if not docs:
        if os.environ.get("ONSIDE_BOOTSTRAP", "quick") == "full":
            print("Building the full archive (all competitions)...", file=sys.stderr, flush=True)
            rc = build.main(["--workers", "12"])
        else:
            print(
                "Building a quick archive: World Cups and Euros. "
                "Set ONSIDE_BOOTSTRAP=full for everything.",
                file=sys.stderr,
                flush=True,
            )
            rc = 0
            for cid in QUICK:
                rc |= build.main(["--competition", str(cid), "--workers", "12"])
        if rc:
            return rc
    return seed.main(["--if-empty"])


if __name__ == "__main__":
    raise SystemExit(main())
