"""The four social sources, each turning its network's posts into `base.Post`.

* Mastodon - public hashtag timelines, no credentials. Accounts that opted out
  of search indexing (`noindex`) or discovery are skipped.
* Bluesky - full-text search, which needs a signed-in session (a free app
  password). Authors who opted out of logged-out viewers are skipped.
* Reddit - r/soccer's newest posts via an approved, app-only OAuth client.
* X - recent search, billed per post read. Off unless a token *and* a daily
  read budget are set; the budget is enforced before every request.

Every source is read-only and keeps only what the feed shows.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any

import httpx

from ..config import settings
from .base import (
    MAX_AGE_S,
    USER_AGENT,
    Plan,
    Post,
    blocked,
    classify,
    is_football,
    parse_time,
    plain_text,
)

log = logging.getLogger("onside.social")


def _client() -> httpx.Client:
    return httpx.Client(timeout=15.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True)


def _keep(post: Post, plan: Plan, via: str) -> Post | None:
    """Place the post against the topics; drop it if it is too old or is not
    about football at all."""
    if not post["ts"] or time.time() - post["ts"] > MAX_AGE_S:
        return None
    topics = classify(post["text"], plan.topics, via)
    if not is_football(post["text"], topics):
        return None
    post["topics"] = topics
    post["via"] = via
    return post


def _all_failed(failures: list[Exception], total: int) -> None:
    """One slow or failing request costs only its own query; the source as a
    whole fails only if every query did."""
    if total and len(failures) == total:
        raise RuntimeError(f"all {total} requests failed ({type(failures[-1]).__name__})")


class Mastodon:
    name = "mastodon"

    def __init__(self, instance: str | None = None, http: httpx.Client | None = None) -> None:
        self.base = (instance or settings().mastodon_instance).rstrip("/")
        self.http = http or _client()

    def state(self) -> tuple[str, str]:
        return "on", f"Public hashtag timelines from {self.base.split('//')[-1]}. No key needed."

    def collect(self, plan: Plan) -> list[Post]:
        out: list[Post] = []
        failures: list[Exception] = []
        for tag, via in plan.mastodon:
            try:
                r = self.http.get(f"{self.base}/api/v1/timelines/tag/{tag}", params={"limit": 40})
                r.raise_for_status()
                statuses = r.json()
            except (httpx.HTTPError, ValueError) as exc:
                failures.append(exc)
                log.info("mastodon #%s failed (%s); carrying on", tag, type(exc).__name__)
                continue
            for s in statuses:
                post = self.normalise(s)
                if post and (kept := _keep(post, plan, via)):
                    out.append(kept)
        _all_failed(failures, len(plan.mastodon))
        return out

    @staticmethod
    def normalise(s: dict[str, Any]) -> Post | None:
        acct = s.get("account") or {}
        if (
            s.get("sensitive")
            or s.get("spoiler_text")
            or s.get("visibility") != "public"
            or s.get("in_reply_to_id")
            or s.get("reblog")
            or acct.get("noindex")
            or acct.get("discoverable") is False
        ):
            return None
        text = plain_text(s.get("content", ""))
        if not text:
            return None
        return {
            "id": f"mastodon:{s['uri']}",
            "network": "mastodon",
            "url": s.get("url") or s.get("uri"),
            "author": {
                "name": acct.get("display_name") or acct.get("username", ""),
                "handle": f"@{acct.get('acct', '')}",
                "avatar": acct.get("avatar_static") or acct.get("avatar") or "",
                "url": acct.get("url", ""),
            },
            "text": text[:1200],
            "createdAt": s.get("created_at", ""),
            "ts": parse_time(s.get("created_at", "")),
            "lang": s.get("language") or "",
            "metrics": {
                "likes": s.get("favourites_count", 0),
                "reposts": s.get("reblogs_count", 0),
                "replies": s.get("replies_count", 0),
            },
            "media": [
                {"thumb": m.get("preview_url", ""), "alt": m.get("description") or ""}
                for m in s.get("media_attachments") or []
                if m.get("type") == "image" and m.get("preview_url")
            ][:4],
        }


class Bluesky:
    name = "bluesky"
    SERVICE = "https://bsky.social"

    def __init__(
        self,
        handle: str | None = None,
        password: str | None = None,
        http: httpx.Client | None = None,
    ) -> None:
        s = settings()
        self.handle = handle if handle is not None else s.bluesky_handle
        self.password = password if password is not None else s.bluesky_app_password
        self.http = http or _client()
        self._access = ""
        self._refresh = ""
        self._at = 0.0

    def state(self) -> tuple[str, str]:
        if not (self.handle and self.password):
            return (
                "needs_key",
                "Set BLUESKY_HANDLE and BLUESKY_APP_PASSWORD (a free app password from "
                "Bluesky settings) to search Bluesky.",
            )
        return "on", f"Searching Bluesky as {self.handle}, read-only."

    def _session(self) -> str:
        """A session token, refreshed rather than re-created: Bluesky rate-
        limits sign-ins far more tightly than refreshes."""
        if self._access and time.time() - self._at < 90 * 60:
            return self._access
        if self._refresh:
            r = self.http.post(
                f"{self.SERVICE}/xrpc/com.atproto.server.refreshSession",
                headers={"Authorization": f"Bearer {self._refresh}"},
            )
            if r.status_code == 200:
                return self._store(r.json())
        r = self.http.post(
            f"{self.SERVICE}/xrpc/com.atproto.server.createSession",
            json={"identifier": self.handle, "password": self.password},
        )
        if r.status_code != 200:
            raise RuntimeError(
                "Bluesky refused the sign-in - check BLUESKY_HANDLE and the app password."
            )
        return self._store(r.json())

    def _store(self, body: dict[str, Any]) -> str:
        self._access, self._refresh, self._at = body["accessJwt"], body["refreshJwt"], time.time()
        return self._access

    def collect(self, plan: Plan) -> list[Post]:
        out: list[Post] = []
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=MAX_AGE_S)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        token = self._session()  # a refused sign-in fails the whole source, clearly
        failures: list[Exception] = []
        for query, via in plan.bluesky:
            try:
                r = self.http.get(
                    f"{self.SERVICE}/xrpc/app.bsky.feed.searchPosts",
                    params={"q": query, "sort": "latest", "limit": 25, "since": since},
                    headers={"Authorization": f"Bearer {token}"},
                )
                if r.status_code == 401:  # token expired early; sign in again next cycle
                    self._access = ""
                r.raise_for_status()
                found = r.json().get("posts", [])
            except (httpx.HTTPError, ValueError) as exc:
                failures.append(exc)
                log.info("bluesky search failed (%s); carrying on", type(exc).__name__)
                continue
            for p in found:
                post = self.normalise(p)
                if post and (kept := _keep(post, plan, via)):
                    out.append(kept)
        _all_failed(failures, len(plan.bluesky))
        return out

    @staticmethod
    def normalise(p: dict[str, Any]) -> Post | None:
        author = p.get("author") or {}
        record = p.get("record") or {}
        labels = [x.get("val", "") for x in (p.get("labels") or []) + (author.get("labels") or [])]
        if blocked(labels) or record.get("reply"):
            return None
        text = (record.get("text") or "").strip()
        if not text:
            return None
        rkey = p["uri"].rsplit("/", 1)[-1]
        handle = author.get("handle", "")
        embed = p.get("embed") or {}
        images = embed.get("images") or (embed.get("media") or {}).get("images") or []
        return {
            "id": f"bluesky:{p['uri']}",
            "network": "bluesky",
            "url": f"https://bsky.app/profile/{handle}/post/{rkey}",
            "author": {
                "name": author.get("displayName") or handle,
                "handle": f"@{handle}",
                "avatar": author.get("avatar") or "",
                "url": f"https://bsky.app/profile/{handle}",
            },
            "text": text[:1200],
            "createdAt": record.get("createdAt", ""),
            "ts": parse_time(record.get("createdAt", "")),
            "lang": (record.get("langs") or [""])[0],
            "metrics": {
                "likes": p.get("likeCount", 0),
                "reposts": p.get("repostCount", 0),
                "replies": p.get("replyCount", 0),
            },
            "media": [{"thumb": i.get("thumb", ""), "alt": i.get("alt") or ""} for i in images][:4],
        }


class Reddit:
    name = "reddit"

    def __init__(
        self,
        client_id: str | None = None,
        secret: str | None = None,
        http: httpx.Client | None = None,
    ) -> None:
        s = settings()
        self.client_id = client_id if client_id is not None else s.reddit_client_id
        self.secret = secret if secret is not None else s.reddit_client_secret
        self.http = http or _client()
        self._token, self._exp = "", 0.0

    def state(self) -> tuple[str, str]:
        if not (self.client_id and self.secret):
            return (
                "needs_key",
                "Reddit approves every new API app by hand. Once approved, set "
                "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET.",
            )
        return "on", "r/soccer's newest posts, read-only."

    def _auth(self) -> str:
        if self._token and time.time() < self._exp - 60:
            return self._token
        r = self.http.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.secret),
        )
        r.raise_for_status()
        body = r.json()
        self._token, self._exp = (
            body["access_token"],
            time.time() + float(body.get("expires_in", 3600)),
        )
        return self._token

    def collect(self, plan: Plan) -> list[Post]:
        r = self.http.get(
            "https://oauth.reddit.com/r/soccer/new",
            params={"limit": 100, "raw_json": 1},
            headers={"Authorization": f"Bearer {self._auth()}"},
        )
        r.raise_for_status()
        out = []
        for child in r.json().get("data", {}).get("children", []):
            post = self.normalise(child.get("data") or {})
            if post and (kept := _keep(post, plan, "")):
                out.append(kept)
        return out

    @staticmethod
    def normalise(d: dict[str, Any]) -> Post | None:
        if d.get("over_18") or d.get("stickied") or not d.get("title"):
            return None
        body = (d.get("selftext") or "").strip()
        text = d["title"] + (f"\n\n{body[:600]}" if body else "")
        created = float(d.get("created_utc") or 0)
        thumb = d.get("thumbnail") or ""
        return {
            "id": f"reddit:{d['id']}",
            "network": "reddit",
            "url": f"https://www.reddit.com{d.get('permalink', '')}",
            "author": {
                "name": f"u/{d.get('author', '')}",
                "handle": f"u/{d.get('author', '')}",
                "avatar": "",
                "url": f"https://www.reddit.com/user/{d.get('author', '')}",
            },
            "text": text,
            "createdAt": dt.datetime.fromtimestamp(created, dt.timezone.utc).isoformat(),
            "ts": created,
            "lang": "en",
            "metrics": {
                "likes": d.get("score", 0),
                "reposts": 0,
                "replies": d.get("num_comments", 0),
            },
            "media": [{"thumb": thumb, "alt": d["title"]}] if thumb.startswith("https://") else [],
        }


class X:
    name = "x"

    def __init__(
        self,
        token: str | None = None,
        daily_budget: int | None = None,
        r: Any = None,
        http: httpx.Client | None = None,
    ) -> None:
        s = settings()
        self.token = token if token is not None else s.x_bearer_token
        self.budget = daily_budget if daily_budget is not None else s.x_max_reads_per_day
        self.r = r
        self.http = http or _client()

    def state(self) -> tuple[str, str]:
        if not self.token:
            return (
                "paid_off",
                "X has no free API. Reads cost about $0.005 each; set X_BEARER_TOKEN and "
                "X_MAX_READS_PER_DAY to switch it on with a hard daily cap.",
            )
        if self.budget <= 0:
            return "paid_off", "X_BEARER_TOKEN is set but X_MAX_READS_PER_DAY is 0, so X stays off."
        return "on", f"Recent search, capped at {self.budget} post reads a day."

    def _spent_key(self) -> str:
        return f"social:x:reads:{dt.date.today().isoformat()}"

    def remaining(self) -> int:
        spent = int(self.r.get(self._spent_key()) or 0) if self.r is not None else 0
        return max(0, self.budget - spent)

    def collect(self, plan: Plan) -> list[Post]:
        out: list[Post] = []
        for query, via in plan.x:
            n = min(10, self.remaining())
            if n < 10:  # the API's smallest page; stop rather than overspend
                break
            r = self.http.get(
                "https://api.x.com/2/tweets/search/recent",
                params={
                    "query": query,
                    "max_results": n,
                    "tweet.fields": "created_at,public_metrics,lang,possibly_sensitive",
                    "expansions": "author_id",
                    "user.fields": "name,username,profile_image_url",
                },
                headers={"Authorization": f"Bearer {self.token}"},
            )
            r.raise_for_status()
            body = r.json()
            tweets = body.get("data") or []
            if self.r is not None:
                self.r.incrby(self._spent_key(), len(tweets))
                self.r.expire(self._spent_key(), 3 * 86400)
            users = {u["id"]: u for u in (body.get("includes") or {}).get("users", [])}
            for t in tweets:
                post = self.normalise(t, users.get(t.get("author_id", ""), {}))
                if post and (kept := _keep(post, plan, via)):
                    out.append(kept)
        return out

    @staticmethod
    def normalise(t: dict[str, Any], user: dict[str, Any]) -> Post | None:
        if t.get("possibly_sensitive"):
            return None
        m = t.get("public_metrics") or {}
        username = user.get("username", "")
        return {
            "id": f"x:{t['id']}",
            "network": "x",
            "url": f"https://x.com/{username or 'i'}/status/{t['id']}",
            "author": {
                "name": user.get("name", username),
                "handle": f"@{username}",
                "avatar": user.get("profile_image_url", ""),
                "url": f"https://x.com/{username}",
            },
            "text": t.get("text", ""),
            "createdAt": t.get("created_at", ""),
            "ts": parse_time(t.get("created_at", "")),
            "lang": t.get("lang") or "",
            "metrics": {
                "likes": m.get("like_count", 0),
                "reposts": m.get("retweet_count", 0),
                "replies": m.get("reply_count", 0),
            },
            "media": [],
        }
