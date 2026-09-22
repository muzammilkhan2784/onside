"""Where collected posts live: Redis, for three days.

    social:post:<id>        the post, JSON, expires after 72 h
    social:all              sorted set of every post id by time
    social:net:<network>    ... by network
    social:topic:<topic>    ... by fixture id or competition code
    social:tagged           "<hashtag>#<post id>" by time, for the trends panel
    social:topics           the current topics (labels for the dashboard)
    social:sources          each source's state, as the worker last saw it

Sorted sets are trimmed on every write, and a post whose body has expired is
skipped when read, so nothing grows without bound.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from typing import Any

from .base import MAX_AGE_S, Post

KEEP_ALL, KEEP_EACH = 3000, 600
NETWORKS = ("bluesky", "mastodon", "reddit", "x")
HASHTAG = re.compile(r"#([A-Za-z][\w]{2,30})")


def post_key(pid: str) -> str:
    return f"social:post:{pid}"


URL = re.compile(r"https?://\S+")
AUTHOR_CAP, AUTHOR_WINDOW_S = 8, 6 * 3600


def fingerprint(p: Post) -> str:
    """Same author, same words (links aside): the same post, however many
    times a bot sends it."""
    words = " ".join(URL.sub("", p["text"]).lower().split())[:160]
    return hashlib.sha1(f"{p['network']}|{p['author']['handle']}|{words}".encode()).hexdigest()


def fresh(r: Any, posts: list[Post]) -> list[Post]:
    """Drop repeats and cap any one account at eight posts every six hours,
    so a single busy bot cannot bury everyone else."""
    out: list[Post] = []
    # One round trip to learn which posts are already stored. Those are left
    # alone: every cycle finds the same posts again, and rewriting them would
    # cost a write each for nothing.
    stored = r.mget([post_key(p["id"]) for p in posts]) if posts else []
    for p, already in zip(posts, stored, strict=True):
        if already is not None:
            continue
        if not r.set(f"social:fp:{fingerprint(p)}", p["id"], nx=True, ex=MAX_AGE_S):
            continue
        author = f"social:author:{p['network']}:{p['author']['handle']}"
        n = r.incr(author)
        if n == 1:
            r.expire(author, AUTHOR_WINDOW_S)
        if n > AUTHOR_CAP:
            continue
        out.append(p)
    return out


def save(r: Any, posts: list[Post]) -> int:
    unique: dict[str, Post] = {}
    for p in posts:  # the same post found by two queries keeps both topics
        if p["id"] in unique:
            seen = unique[p["id"]]["topics"]
            seen.extend(t for t in p["topics"] if t not in seen)
        else:
            unique[p["id"]] = {**p, "topics": list(p["topics"])}
    posts = fresh(r, list(unique.values()))
    if not posts:
        return 0
    pipe = r.pipeline(transaction=False)
    touched = {"social:all"}
    for p in posts:
        pipe.set(post_key(p["id"]), json.dumps(p, separators=(",", ":")), ex=MAX_AGE_S)
        pipe.zadd("social:all", {p["id"]: p["ts"]})
        pipe.zadd(f"social:net:{p['network']}", {p["id"]: p["ts"]})
        touched.add(f"social:net:{p['network']}")
        for t in p.get("topics", []):
            pipe.zadd(f"social:topic:{t}", {p["id"]: p["ts"]})
            touched.add(f"social:topic:{t}")
        # Hashtags get an index of their own, so the trends panel counts
        # small index entries instead of loading every recent post.
        tags = {tag.lower() for tag in HASHTAG.findall(p["text"])}
        if tags:
            pipe.zadd("social:tagged", {f"{tag}#{p['id']}": p["ts"] for tag in tags})
            touched.add("social:tagged")
    for key in touched:
        keep = KEEP_ALL if key in ("social:all", "social:tagged") else KEEP_EACH
        pipe.zremrangebyrank(key, 0, -keep - 1)
        pipe.zremrangebyscore(key, "-inf", time.time() - MAX_AGE_S)
    pipe.execute()
    return len(posts)


def set_source(r: Any, name: str, state: str, message: str, count: int | None = None) -> None:
    r.hset(
        "social:sources",
        name,
        json.dumps({"state": state, "message": message, "count": count, "at": time.time()}),
    )


def set_topics(r: Any, topics: list[dict[str, Any]]) -> None:
    r.set("social:topics", json.dumps(topics, separators=(",", ":")))


def _load(r: Any, ids: list[str]) -> list[Post]:
    if not ids:
        return []
    return [json.loads(raw) for raw in r.mget([post_key(i) for i in ids]) if raw]


def page(
    r: Any,
    *,
    topic: str | None = None,
    network: str | None = None,
    lang: str | None = None,
    before: float | None = None,
    limit: int = 30,
) -> tuple[list[Post], float | None]:
    """Newest first. Filters that have no index of their own (network within a
    topic, language) are applied while scanning, a hundred ids at a time."""
    if topic and topic != "all":
        key = f"social:topic:{topic}"
    elif network:
        key = f"social:net:{network}"
    else:
        key = "social:all"
    high: float | str = f"({before}" if before else "+inf"
    out: list[Post] = []
    scanned, chunk = 0, 100
    while len(out) < limit and scanned < 1500:
        rows = r.zrevrangebyscore(key, high, "-inf", start=0, num=chunk, withscores=True)
        if not rows:
            break
        scanned += len(rows)
        for p in _load(r, [member for member, _ in rows]):
            if network and p["network"] != network:
                continue
            if lang and p.get("lang") and not p["lang"].startswith(lang):
                continue
            out.append(p)
            if len(out) == limit:
                break
        high = f"({rows[-1][1]}"
        if len(rows) < chunk:
            break
    nxt = out[-1]["ts"] if len(out) == limit else None
    return out, nxt


def overview(r: Any) -> dict[str, Any]:
    """Everything the dashboard's side panels need. Only index entries are
    read - ids, times and hashtags - never the posts themselves: a post id
    starts with its network, and that is all the volume chart needs."""
    now = time.time()
    sources = {k: json.loads(v) for k, v in (r.hgetall("social:sources") or {}).items()}
    for name in NETWORKS:
        sources.setdefault(name, {"state": "off", "message": "Not started yet.", "count": None})
    topics = json.loads(r.get("social:topics") or "[]")
    for t in topics:
        t["posts"] = int(r.zcount(f"social:topic:{t['id']}", now - 24 * 3600, "+inf"))
    recent = r.zrevrangebyscore(
        "social:all", "+inf", now - 12 * 3600, start=0, num=KEEP_ALL, withscores=True
    )
    tagged = r.zrevrangebyscore("social:tagged", "+inf", now - 6 * 3600, start=0, num=KEEP_ALL)
    tags = Counter(entry.split("#", 1)[0] for entry in tagged)
    hours: list[dict[str, Any]] = []
    for h in range(11, -1, -1):
        lo, hi = now - (h + 1) * 3600, now - h * 3600
        row: dict[str, Any] = {"hoursAgo": h}
        for n in NETWORKS:
            row[n] = sum(1 for pid, ts in recent if pid.startswith(f"{n}:") and lo <= ts < hi)
        hours.append(row)
    return {
        "sources": sources,
        "topics": topics,
        "trends": [{"tag": t, "posts": c} for t, c in tags.most_common(12)],
        "volume": hours,
        "total24h": int(r.zcount("social:all", now - 24 * 3600, "+inf")),
    }
