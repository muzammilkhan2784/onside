"""Competitions, standings, teams and the search index - derived from the
match documents.

Two honesty rules shape this module:

* **No table from partial coverage.** StatsBomb's La Liga seasons are mostly
  Barcelona's matches. A "table" built from them would put Barcelona top of a
  league of teams that played once. So a league table is only built when the
  archive holds (nearly) the full fixture list; otherwise the season says how
  many matches it has and why there is no table.
* **Groups are inferred, and say so.** StatsBomb does not record group letters.
  Groups are recovered as the connected components of the group-stage fixture
  graph, numbered by first kick-off, and labelled that way.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from ..domain.tables import Result, compute

#: Competition id -> tie-break strategy id in domain.tables.
LEAGUE_RULES: dict[int, str] = {
    2: "PL",  # Premier League
    11: "LIGA",  # La Liga
    12: "SERIE_A",  # Serie A
    9: "BUNDESLIGA",  # 1. Bundesliga
    7: "LIGUE_1",  # Ligue 1
    37: "PL",  # FA Women's Super League (goal difference first)
    49: "PL",  # NWSL
    44: "PL",  # MLS
    81: "PL",  # Liga Profesional
    1238: "PL",  # Indian Super League
    116: "PL",
    182: "LIGA",  # Liga F
    135: "BUNDESLIGA",  # Frauen-Bundesliga
    131: "SERIE_A",  # Serie A Women
}

GROUP_RULES: dict[int, str] = {
    55: "UEFA_EURO_GROUP",  # UEFA Euro
    53: "UEFA_EURO_GROUP",  # UEFA Women's Euro
}
DEFAULT_GROUP_RULE = "FIFA_GROUP"

#: Below this share of the full double round-robin, no league table is shown.
MIN_LEAGUE_COVERAGE = 0.9


def _results(cards: Iterable[dict[str, Any]]) -> list[Result]:
    return [
        Result(c["home"]["id"], c["away"]["id"], int(c["score"][0]), int(c["score"][1]))
        for c in cards
    ]


def _names(cards: Iterable[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in cards:
        out[c["home"]["id"]] = c["home"]["name"]
        out[c["away"]["id"]] = c["away"]["name"]
    return out


def _table_doc(group: str, table: Any, names: dict[str, str], note: str = "") -> dict[str, Any]:
    return {
        "group": group,
        "ruleId": table.rule_id,
        "explanation": table.explanation,
        "note": note,
        "unresolved": [list(g) for g in table.unresolved],
        "rows": [
            {
                "position": i + 1,
                "teamId": r.team_id,
                "team": names.get(r.team_id, r.team_id),
                "played": r.played,
                "won": r.won,
                "drawn": r.drawn,
                "lost": r.lost,
                "goalsFor": r.goals_for,
                "goalsAgainst": r.goals_against,
                "goalDifference": r.goal_difference,
                "points": r.points,
            }
            for i, r in enumerate(table.rows)
        ],
    }


def infer_groups(cards: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Connected components of the group-stage fixture graph, ordered by first kick-off."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for c in cards:
        a, b = find(c["home"]["id"]), find(c["away"]["id"])
        if a != b:
            parent[a] = b
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in cards:
        groups[find(c["home"]["id"])].append(c)
    return sorted(groups.values(), key=lambda g: min(f"{c['date']}{c['kickoff']}" for c in g))


def season_tables(
    competition_id: int, international: bool, cards: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str]:
    """Return (tables, coverage note). An empty list means no honest table exists."""
    names = _names(cards)
    group_stage = [c for c in cards if c.get("stage") == "Group Stage"]

    if group_stage:
        rule = GROUP_RULES.get(competition_id, DEFAULT_GROUP_RULE)
        tables = []
        for i, g in enumerate(infer_groups(group_stage), start=1):
            teams = {c["home"]["id"] for c in g} | {c["away"]["id"] for c in g}
            expected = len(teams) * (len(teams) - 1) // 2
            note = (
                ""
                if len(g) >= expected
                else f"{len(g)} of {expected} group matches are in the archive."
            )
            tables.append(
                _table_doc(
                    f"Group {i}", compute(_results(g), competition=rule, names=names), names, note
                )
            )
        note = (
            "StatsBomb does not record group letters, so groups are recovered from who played "
            "whom and numbered in the order they kicked off."
        )
        return tables, note

    if international or competition_id not in LEAGUE_RULES:
        return (
            [],
            "This is a knockout competition, so there is no table - every match here is a tie.",
        )

    teams = set(names)
    expected = len(teams) * (len(teams) - 1)
    coverage = len(cards) / expected if expected else 0.0
    if coverage < MIN_LEAGUE_COVERAGE:
        return [], (
            f"The open data holds {len(cards)} of this season's {expected} league matches - mostly "
            f"one club's fixtures. A table built from them would be wrong, so none is shown."
        )
    table = compute(_results(cards), competition=LEAGUE_RULES[competition_id], names=names)
    return [_table_doc("League", table, names)], ""


def team_catalog(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every team with its record across the archive."""
    teams: dict[str, dict[str, Any]] = {}
    for c in cards:
        for side in ("home", "away"):
            t = c[side]
            e = teams.setdefault(
                t["id"],
                {
                    "id": t["id"],
                    "name": t["name"],
                    "matches": 0,
                    "won": 0,
                    "drawn": 0,
                    "lost": 0,
                    "goalsFor": 0,
                    "goalsAgainst": 0,
                    "xgFor": 0.0,
                    "xgAgainst": 0.0,
                    "competitions": set(),
                    "first": c["date"],
                    "last": c["date"],
                },
            )
            gf = c["score"][0 if side == "home" else 1]
            ga = c["score"][1 if side == "home" else 0]
            e["matches"] += 1
            e["goalsFor"] += gf
            e["goalsAgainst"] += ga
            e["xgFor"] += c["xg"][0 if side == "home" else 1] or 0
            e["xgAgainst"] += c["xg"][1 if side == "home" else 0] or 0
            e["won" if gf > ga else ("drawn" if gf == ga else "lost")] += 1
            e["competitions"].add(c["competition"]["name"])
            e["first"] = min(e["first"], c["date"])
            e["last"] = max(e["last"], c["date"])
    out = []
    for e in teams.values():
        e["competitions"] = sorted(e["competitions"])
        e["xgFor"] = round(e["xgFor"], 1)
        e["xgAgainst"] = round(e["xgAgainst"], 1)
        out.append(e)
    return sorted(out, key=lambda e: -e["matches"])


def competition_catalog(
    cards: list[dict[str, Any]], comps_raw: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Competitions -> seasons, with match counts and date ranges."""
    by_cs: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for c in cards:
        by_cs[(c["competition"]["id"], c["season"]["id"])].append(c)
    comps: dict[str, dict[str, Any]] = {}
    for cs in comps_raw:
        cid, sid = str(cs["competition_id"]), str(cs["season_id"])
        season_cards = by_cs.get((cid, sid), [])
        if not season_cards:
            continue
        comp = comps.setdefault(
            cid,
            {
                "id": cid,
                "name": cs["competition_name"],
                "country": cs.get("country_name", ""),
                "gender": cs.get("competition_gender", ""),
                "international": bool(cs.get("competition_international")),
                "youth": bool(cs.get("competition_youth")),
                "seasons": [],
                "matches": 0,
            },
        )
        dates = sorted(c["date"] for c in season_cards)
        comp["seasons"].append(
            {
                "id": sid,
                "name": cs["season_name"],
                "matches": len(season_cards),
                "from": dates[0],
                "to": dates[-1],
            }
        )
        comp["matches"] += len(season_cards)
    for comp in comps.values():
        comp["seasons"].sort(key=lambda s: s["to"], reverse=True)
    return sorted(comps.values(), key=lambda c: -c["matches"])
