"""Inline the match payload into the demo page.

The published page has to be self-contained: the artifact sandbox blocks
same-origin fetch of sibling files in some contexts, and a demo that fails to
load its own data is worse than no demo. So the payload - real events, the
real exported model - is inlined at build time.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
TEMPLATE = HERE / "index.template.html"
PAYLOAD = HERE / "match.json"
OUT = HERE / "index.html"

PLACEHOLDER = "__ONSIDE_DATA__"


def main() -> None:
    data = json.loads(PAYLOAD.read_text(encoding="utf-8"))
    html = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise SystemExit(f"{TEMPLATE.name} has no {PLACEHOLDER} placeholder")

    # `</script>` inside a JSON string would close the host script tag early.
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    OUT.write_text(html.replace(PLACEHOLDER, blob), encoding="utf-8")

    kb = OUT.stat().st_size / 1024
    model = data.get("model") or {}
    print(f"Built {OUT} ({kb:.0f} KB)")
    print(f"  {len(data['goals'])} goals, {len(data['shots'])} shots, "
          f"{len(data['corrections'])} corrections, {model.get('n_trees', 0)} model trees")


if __name__ == "__main__":
    main()
