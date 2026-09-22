"""/m/{match_id} - the match on a bad connection.

Server-rendered HTML, no JavaScript, one inline stylesheet, well under 100 KB
(asserted in tests/integration/test_api.py). Proper semantics so a screen
reader gets the same match everyone else does: `<time>`, real `<table>`s, and
an ARIA live region around the score, which a live page refreshes with a meta
refresh rather than a script.
"""

from __future__ import annotations

from html import escape
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ..store import repo
from .deps import match_state

router = APIRouter(tags=["lite"])

CSS = """
body{font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;margin:0 auto;max-width:44rem;padding:1rem;
color:#111;background:#fff}h1{font-size:1.4rem;margin:.2rem 0}.score{font-size:2.4rem;font-weight:800}
table{border-collapse:collapse;width:100%;margin:.6rem 0}td,th{padding:.3rem .4rem;border-bottom:1px solid #ddd;
text-align:left}td.n{text-align:right;font-variant-numeric:tabular-nums}s{color:#8a6100}
.meta{color:#555;font-size:.9rem}.note{background:#fff7e0;border-left:4px solid #e0a800;padding:.5rem .8rem}
ol{padding-left:1.2rem}@media(prefers-color-scheme:dark){body{background:#111;color:#eee}td,th{border-color:#333}
.meta{color:#aaa}.note{background:#2a2100}}
""".replace("\n", "")


def _e(v: Any) -> str:
    return escape(str(v if v is not None else ""))


def render(state: dict[str, Any], report: dict[str, Any]) -> str:
    h, a = state["score"]
    home, away = state["home"]["name"], state["away"]["name"]
    live = state.get("live") and state.get("status") != "finished"
    clock = state.get("clock") or {}
    status = f"{clock.get('minute', '')}' - live" if live else "Full time"
    pens = (
        f" ({state['shootout'][0]}-{state['shootout'][1]} on penalties)"
        if state.get("shootout")
        else ""
    )

    goals = []
    for g in state["goals"]:
        side = home if g["home"] else away
        text = f"{_e(g['minute'])}' {_e(g['player'])} ({_e(side)}){' - penalty' if g['type'] == 'Penalty' else ''}"
        if g.get("disallowed"):
            text = f"<s>{text}</s> - disallowed: {_e(g.get('correctionReason', ''))}"
        goals.append(f"<li>{text}</li>")

    stat_rows = []
    for key, label in (
        ("xg", "Expected goals"),
        ("shots", "Shots"),
        ("shotsOnTarget", "On target"),
        ("possession", "Possession"),
        ("passAccuracy", "Pass accuracy"),
    ):
        hv, av = state["stats"]["home"][key], state["stats"]["away"][key]
        if key in ("possession", "passAccuracy"):
            hv, av = f"{hv * 100:.0f}%", f"{av * 100:.0f}%"
        stat_rows.append(
            f"<tr><td class=n>{_e(hv)}</td><th scope=row>{label}</th><td>{_e(av)}</td></tr>"
        )

    corr = ""
    if state.get("corrections"):
        items = "".join(
            f"<li>{_e(c['decidedAt'])}' - {_e(c['headline'])}"
            f"{' (synthesised for this replay)' if c.get('synthesised') else ''}</li>"
            for c in state["corrections"]
        )
        corr = f"<h2>Corrections</h2><ol>{items}</ol>"

    lines = "".join(f"<li>{_e(line)}</li>" for line in report.get("lines", []))
    refresh = '<meta http-equiv="refresh" content="20">' if live else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{refresh}
<title>{_e(home)} {h}-{a} {_e(away)} - Onside</title><style>{CSS}</style></head><body>
<p class="meta">{_e(state["competition"]["name"])} &middot; {_e(state["season"]["name"])}
&middot; <time datetime="{_e(state["date"])}">{_e(state["date"])}</time></p>
<h1>{_e(home)} v {_e(away)}</h1>
<p class="score" aria-live="polite" aria-atomic="true">{h}-{a}{_e(pens)} <small>{_e(status)}</small></p>
<h2>Goals</h2>{"<ol>" + "".join(goals) + "</ol>" if goals else "<p>No goals.</p>"}
{corr}
<h2>Stats</h2><table><caption class="meta">{_e(home)} left, {_e(away)} right</caption>{"".join(stat_rows)}</table>
<h2>What happened</h2><p>{_e(report.get("lede", ""))}</p><ol>{lines}</ol>
<p class="meta">Event data: StatsBomb Open Data. Full interactive page: <a href="/match/{_e(state["id"])}">open</a>.</p>
</body></html>"""


@router.get(
    "/m/{match_id}", response_class=HTMLResponse, summary="Low-bandwidth match page (no JavaScript)"
)
def lite(match_id: str) -> HTMLResponse:
    state = match_state(match_id)
    report = (repo.get_part(match_id, "REPORT") or {}).get("report") or {}
    return HTMLResponse(render(state, report), headers={"Cache-Control": "public, max-age=30"})
