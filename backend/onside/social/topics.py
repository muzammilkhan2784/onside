"""From the current fixtures to what the social sources should look for.

The feed follows the football: the matches being played now, about to kick
off, or just finished, and the competitions they belong to. Nothing here
calls a network; it turns the fixtures snapshot into topics and queries.
"""

from __future__ import annotations

import re
import time
from typing import Any

from .base import Plan, Topic, fold, parse_time

#: Broadcast order: which competitions come first when there are more matches
#: than a cycle can search for.
PRIORITY = ["CL", "PL", "PD", "BL1", "SA", "FL1", "ELC", "DED", "PPL", "CLI", "BSA", "WC", "EC"]

COMPETITION_ALIASES: dict[str, tuple[str, ...]] = {
    "CL": ("champions league", "ucl", "#ucl", "championsleague"),
    "PL": ("premier league", "epl", "premierleague"),
    "PD": ("la liga", "laliga", "primera division"),
    "BL1": ("bundesliga",),
    "SA": ("serie a", "seriea"),
    "FL1": ("ligue 1", "ligue1"),
    "ELC": ("efl championship", "sky bet championship", "#efl"),
    "DED": ("eredivisie",),
    "PPL": ("primeira liga", "liga portugal"),
    "CLI": ("libertadores",),
    "BSA": ("brasileirao", "brasileirão", "serie a betano"),
    "WC": ("world cup", "worldcup"),
    "EC": ("euro 2028", "euros"),
}
COMPETITION_TAGS: dict[str, tuple[str, ...]] = {
    "CL": ("championsleague", "ucl"),
    "PL": ("premierleague", "epl"),
    "PD": ("laliga",),
    "BL1": ("bundesliga",),
    "SA": ("seriea",),
    "FL1": ("ligue1",),
    "ELC": ("efl",),
    "DED": ("eredivisie",),
    "PPL": ("ligaportugal",),
    "CLI": ("libertadores",),
    "BSA": ("brasileirao",),
}
BLUESKY_COMPETITION_QUERIES = {
    "CL": "Champions League",
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
}

#: Names fans actually use, beyond the feed's short and full names.
TEAM_ALIASES: dict[str, tuple[str, ...]] = {
    "man city": ("manchester city", "mcfc", "city"),
    "man united": ("manchester united", "man utd", "mufc", "united"),
    "tottenham": ("spurs", "tottenham hotspur", "thfc"),
    "arsenal": ("gunners", "afc"),
    "liverpool": ("lfc", "reds"),
    "chelsea": ("cfc", "blues"),
    "newcastle": ("newcastle united", "nufc", "toon"),
    "nott'm forest": ("nottingham forest", "forest", "nffc"),
    "wolverhampton": ("wolves",),
    "west ham": ("west ham united", "whufc", "hammers"),
    "brighton hove": ("brighton", "bhafc", "seagulls"),
    "barca": ("barcelona", "fc barcelona", "barça"),
    "atleti": ("atletico madrid", "atlético madrid", "atletico"),
    "real madrid": ("madrid", "rmcf"),
    "inter": ("inter milan", "internazionale"),
    "milan": ("ac milan",),
    "juventus": ("juve",),
    "bayern": ("bayern munich", "bayern münchen", "fc bayern"),
    "dortmund": ("borussia dortmund", "bvb"),
    "leverkusen": ("bayer leverkusen", "bayer 04"),
    "psg": ("paris saint-germain", "paris sg", "paris saint germain"),
    "marseille": ("olympique de marseille", "om"),
}
SUFFIXES = re.compile(r"\b(fc|cf|afc|sc|ac|ssc|as|cd|ud|sd|rc|fk|sk|bk|if)\b", re.IGNORECASE)

LIVE = {"live", "half_time"}
WINDOW_S = 36 * 3600
MAX_FIXTURES = 10


def team_aliases(team: dict[str, Any]) -> tuple[str, ...]:
    short, full = fold(team.get("name", "")), fold(team.get("fullName", ""))
    names = {short, SUFFIXES.sub("", full).strip(), full}
    for key in (short, SUFFIXES.sub("", full).strip()):
        names.update(TEAM_ALIASES.get(key, ()))
    return tuple(sorted(n for n in names if len(n) >= 2))


def _rank(f: dict[str, Any], now: float) -> tuple[int, int, float]:
    prio = PRIORITY.index(f["competition"]["code"]) if f["competition"]["code"] in PRIORITY else 99
    live = 0 if f["status"] in LIVE else 1
    return (live, prio, abs(parse_time(f["kickoffUtc"]) - now))


def relevant(fixtures: list[dict[str, Any]], now: float | None = None) -> list[dict[str, Any]]:
    """The fixtures worth following: in play, or kicking off or finished within
    a day and a half. Live first, then the bigger competitions, then the
    nearest in time."""
    now = now or time.time()
    keep = [
        f
        for f in fixtures
        if f["status"] in LIVE
        or (
            f["status"] in {"scheduled", "finished"}
            and abs(parse_time(f["kickoffUtc"]) - now) <= WINDOW_S
        )
    ]
    return sorted(keep, key=lambda f: _rank(f, now))[:MAX_FIXTURES]


def _tag(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", fold(name))


def plan(fixtures: list[dict[str, Any]], now: float | None = None) -> Plan:
    picked = relevant(fixtures, now)
    topics: list[Topic] = []
    for f in picked:
        topics.append(
            Topic(
                id=f["id"],
                label=f"{f['home']['name']} v {f['away']['name']}",
                kind="fixture",
                competition=f["competition"]["code"],
                home=team_aliases(f["home"]),
                away=team_aliases(f["away"]),
                meta={
                    "status": f["status"],
                    "kickoffUtc": f["kickoffUtc"],
                    "score": f.get("score"),
                    "home": f["home"],
                    "away": f["away"],
                    "competition": f["competition"],
                },
            )
        )
    codes = []
    for f in sorted(fixtures, key=lambda f: _rank(f, now or time.time())):
        c = f["competition"]["code"]
        if c and c not in codes:
            codes.append(c)
    names = {f["competition"]["code"]: f["competition"]["name"] for f in fixtures}
    for c in codes:
        topics.append(
            Topic(
                id=c,
                label=names.get(c, c),
                kind="competition",
                competition=c,
                names=tuple(
                    fold(n) for n in (names.get(c, ""), *COMPETITION_ALIASES.get(c, ())) if n
                ),
            )
        )

    fixture_topics = [t for t in topics if t.kind == "fixture"]
    bluesky = [
        (f"{t.meta['home']['name']} {t.meta['away']['name']}", t.id) for t in fixture_topics[:8]
    ]
    bluesky += [(q, c) for c, q in BLUESKY_COMPETITION_QUERIES.items() if c in codes][:4]
    mastodon = [("football", ""), ("soccer", "")]
    for c in codes:
        mastodon += [(tag, c) for tag in COMPETITION_TAGS.get(c, ())[:1]]
    for t in fixture_topics[:4]:
        mastodon += [(_tag(t.meta["home"]["name"]), t.id), (_tag(t.meta["away"]["name"]), t.id)]
    live = [t for t in fixture_topics if t.meta["status"] in LIVE]
    x = [
        (f'"{t.meta["home"]["name"]}" "{t.meta["away"]["name"]}" -is:retweet -is:reply', t.id)
        for t in live[:3]
    ]
    seen: set[str] = set()
    mastodon = [(q, v) for q, v in mastodon if q and not (q in seen or seen.add(q))][:14]
    return Plan(topics=topics, bluesky=bluesky[:12], mastodon=mastodon, x=x)
