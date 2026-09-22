"""Repositories over the single table.

Reads return plain dicts shaped for the API; writes take domain objects or
match documents. Nothing outside this package touches boto3.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterable, Iterator, Sequence
from typing import Any

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from ..domain.corrections import Correction
from ..domain.events import CanonicalEvent
from . import keys as K
from .client import pack, table, unpack
from .codec import correction_from_dict, correction_to_dict, event_from_dict, event_to_dict


class VersionConflict(Exception):
    """Another projector wrote this match's state first. Re-read and retry."""


# ---------------------------------------------------------------------------
# pagination
# ---------------------------------------------------------------------------


def encode_cursor(last_key: dict[str, Any] | None) -> str | None:
    if not last_key:
        return None
    return base64.urlsafe_b64encode(json.dumps(last_key).encode()).decode()


def decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    if not cursor:
        return None
    try:
        return dict(json.loads(base64.urlsafe_b64decode(cursor.encode())))
    except (ValueError, json.JSONDecodeError):
        return None


def _query(
    index: str | None,
    pk_name: str,
    pk: str,
    *,
    sk_prefix: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    newest_first: bool = False,
) -> tuple[list[dict[str, Any]], str | None]:
    cond = Key(pk_name).eq(pk)
    if sk_prefix is not None:
        sk_name = pk_name.replace("PK", "SK")
        cond = cond & Key(sk_name).begins_with(sk_prefix)
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": cond,
        "Limit": limit,
        "ScanIndexForward": not newest_first,
    }
    if index:
        kwargs["IndexName"] = index
    start = decode_cursor(cursor)
    if start:
        kwargs["ExclusiveStartKey"] = start
    resp = table().query(**kwargs)
    return resp.get("Items", []), encode_cursor(resp.get("LastEvaluatedKey"))


def _query_all(
    index: str | None, pk_name: str, pk: str, *, sk_prefix: str | None = None
) -> Iterator[dict[str, Any]]:
    cursor = None
    while True:
        items, cursor = _query(index, pk_name, pk, sk_prefix=sk_prefix, limit=500, cursor=cursor)
        yield from items
        if not cursor:
            return


# ---------------------------------------------------------------------------
# match documents
# ---------------------------------------------------------------------------


def match_card(doc: dict[str, Any]) -> dict[str, Any]:
    """The small summary every listing shows - a scoreboard line and a story."""
    story = doc.get("story") or {}
    return {
        "id": doc["id"],
        "competition": doc["competition"],
        "season": doc["season"],
        "date": doc["date"],
        "kickoff": doc.get("kickoff", ""),
        "stage": doc.get("stage", ""),
        "matchWeek": doc.get("matchWeek"),
        "home": {"id": doc["home"]["id"], "name": doc["home"]["name"]},
        "away": {"id": doc["away"]["id"], "name": doc["away"]["name"]},
        "score": doc["score"],
        "shootout": doc.get("shootout"),
        "status": doc.get("status", "finished"),
        "xg": [doc["stats"]["home"]["xg"], doc["stats"]["away"]["xg"]],
        "headline": story.get("headline", ""),
        "standfirst": story.get("standfirst", ""),
        "tags": story.get("tags", []),
        "biggestSwing": story.get("biggestSwing", 0),
        "hasFreezeFrames": any(s.get("freeze") for s in doc.get("shots", [])),
        "live": bool(doc.get("live")),
    }


#: Which document keys go into which item. Split so that the match page's
#: first paint (STATE) is small, and the heavy shot map is fetched only when
#: its tab opens.
PARTS: dict[str, tuple[str, ...]] = {
    K.STATE: (
        "id",
        "competition",
        "season",
        "date",
        "kickoff",
        "matchWeek",
        "stage",
        "stadium",
        "referee",
        "neutral",
        "home",
        "away",
        "score",
        "halfTime",
        "shootout",
        "status",
        "eloDiff",
        "goals",
        "cards",
        "timeline",
        "stats",
        "glossary",
        "lineups",
        "capabilities",
        "eventCount",
        "corrections",
        "source",
        "story",
        "live",
        "clock",
        "version",
    ),
    K.REPORT: ("report",),
    K.WPSERIES: ("winProbability", "winProbabilityRange"),
    K.SHOTS: ("shots",),
    K.PASSNET: ("passNetwork",),
}


def document_items(doc: dict[str, Any]) -> list[dict[str, Any]]:
    mid = doc["id"]
    pk = K.match_pk(mid)
    card = match_card(doc)
    date = doc["date"] or "0000-00-00"
    comp, season = doc["competition"]["id"], doc["season"]["id"]
    parts = [
        {
            "PK": pk,
            "SK": sk,
            "body": pack({f: doc.get(f) for f in fields}),
            "version": int(doc.get("version") or 0),
        }
        for sk, fields in PARTS.items()
    ]
    if doc.get("live"):
        # A replay is listed only under LIVE. It must not appear as a second
        # copy of the archived match in the feed, fixtures or tables.
        return [
            {
                "PK": pk,
                "SK": K.META,
                "GSI1PK": "LIVE",
                "GSI1SK": mid,
                "card": pack(card),
                "date": date,
            },
            *parts,
        ]
    items: list[dict[str, Any]] = [
        {
            "PK": pk,
            "SK": K.META,
            "GSI1PK": K.comp_season(comp, season),
            "GSI1SK": K.dated(date, mid),
            "card": pack(card),
            "date": date,
        },
        {
            "PK": pk,
            "SK": K.DAY,
            "GSI1PK": K.date_pk(date),
            "GSI1SK": K.dated(date, mid),
            "card": pack(card),
        },
        {
            "PK": pk,
            "SK": K.STORY,
            "GSI1PK": K.FEED_PK,
            "GSI1SK": K.dated(date, mid),
            "card": pack(card),
        },
    ]
    for side in ("home", "away"):
        tid = doc[side]["id"]
        items.append(
            {
                "PK": pk,
                "SK": f"TEAM#{tid}",
                "GSI2PK": K.team_pk(tid),
                "GSI2SK": K.dated(date, mid),
                "card": pack(card),
            }
        )
    for tag in card["tags"]:
        items.append(
            {
                "PK": pk,
                "SK": f"TAG#{tag}",
                "GSI2PK": K.tag_pk(tag),
                "GSI2SK": K.dated(date, mid),
                "card": pack(card),
            }
        )
    return items + parts


def put_documents(docs: Iterable[dict[str, Any]]) -> int:
    n = 0
    with table().batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
        for doc in docs:
            for item in document_items(doc):
                batch.put_item(Item=item)
            n += 1
    return n


def get_part(match_id: str, part: str) -> dict[str, Any] | None:
    resp = table().get_item(Key={"PK": K.match_pk(match_id), "SK": part})
    item = resp.get("Item")
    return unpack(item["body"]) if item else None


def get_card(match_id: str) -> dict[str, Any] | None:
    resp = table().get_item(Key={"PK": K.match_pk(match_id), "SK": K.META})
    item = resp.get("Item")
    return unpack(item["card"]) if item else None


def get_document(match_id: str) -> dict[str, Any] | None:
    """Every part of a match in one round trip (BatchGetItem on the five parts -
    a live match's partition also holds thousands of log items, which a query
    would drag in)."""
    from ..config import settings
    from .client import resource

    name = settings().table
    pk = K.match_pk(match_id)
    resp = resource().batch_get_item(
        RequestItems={name: {"Keys": [{"PK": pk, "SK": sk} for sk in PARTS]}}
    )
    items = resp.get("Responses", {}).get(name, [])
    if not items:
        return None
    doc: dict[str, Any] = {}
    for it in sorted(items, key=lambda i: list(PARTS).index(i["SK"])):
        doc.update(unpack(it["body"]))
    return doc


def live_matches() -> list[dict[str, Any]]:
    return [unpack(i["card"]) for i in _query_all("GSI1", "GSI1PK", "LIVE")]


def matches_for_competition_season(competition_id: str, season_id: str) -> list[dict[str, Any]]:
    return [
        unpack(i["card"])
        for i in _query_all("GSI1", "GSI1PK", K.comp_season(competition_id, season_id))
    ]


def matches_on_date(date: str) -> list[dict[str, Any]]:
    return [unpack(i["card"]) for i in _query_all("GSI1", "GSI1PK", K.date_pk(date))]


def matches_for_team(
    team_id: str, limit: int = 50, cursor: str | None = None
) -> tuple[list[dict[str, Any]], str | None]:
    items, nxt = _query(
        "GSI2", "GSI2PK", K.team_pk(team_id), limit=limit, cursor=cursor, newest_first=True
    )
    return [unpack(i["card"]) for i in items], nxt


def feed(
    limit: int = 30, cursor: str | None = None, tag: str | None = None
) -> tuple[list[dict[str, Any]], str | None]:
    """The news feed: every match's story, newest first."""
    if tag:
        items, nxt = _query(
            "GSI2", "GSI2PK", K.tag_pk(tag), limit=limit, cursor=cursor, newest_first=True
        )
    else:
        items, nxt = _query(
            "GSI1", "GSI1PK", K.FEED_PK, limit=limit, cursor=cursor, newest_first=True
        )
    return [unpack(i["card"]) for i in items], nxt


# ---------------------------------------------------------------------------
# the live event log - append-only, conditional, versioned
# ---------------------------------------------------------------------------


def append_event(e: CanonicalEvent) -> bool:
    """Append once. Returns False if this event id was already in the log -
    feeds redeliver on reconnect, and a redelivery must be a no-op."""
    try:
        table().put_item(
            Item={
                "PK": K.match_pk(e.match_id),
                "SK": K.event_sk(e.index, e.event_id),
                "body": pack(event_to_dict(e)),
                "received_at": int(time.time() * 1000),
            },
            ConditionExpression=Attr("SK").not_exists(),
        )
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def append_events(events: Sequence[CanonicalEvent]) -> int:
    """Bulk append for seeding a replay. Not conditional - use only on an empty log."""
    with table().batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
        for e in events:
            batch.put_item(
                Item={
                    "PK": K.match_pk(e.match_id),
                    "SK": K.event_sk(e.index, e.event_id),
                    "body": pack(event_to_dict(e)),
                }
            )
    return len(events)


def append_correction(c: Correction) -> bool:
    try:
        table().put_item(
            Item={
                "PK": K.match_pk(c.match_id),
                "SK": K.correction_sk(c.decided_at_minute, c.period, c.correction_id),
                "body": pack(correction_to_dict(c)),
            },
            ConditionExpression=Attr("SK").not_exists(),
        )
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def read_log(match_id: str) -> tuple[list[CanonicalEvent], list[Correction]]:
    pk = K.match_pk(match_id)
    events = [
        event_from_dict(unpack(i["body"])) for i in _query_all(None, "PK", pk, sk_prefix="EVT#")
    ]
    corrections = [
        correction_from_dict(unpack(i["body"]))
        for i in _query_all(None, "PK", pk, sk_prefix="CORR#")
    ]
    return events, corrections


def list_corrections(match_id: str) -> list[dict[str, Any]]:
    return [
        unpack(i["body"]) for i in _query_all(None, "PK", K.match_pk(match_id), sk_prefix="CORR#")
    ]


def clear_log(match_id: str) -> int:
    """Remove a replay's event log so the replay can start over. Only ever used
    by the replay engine on its own demo matches - the append-only rule is about
    a match's history, and a restarted replay is a new history."""
    pk = K.match_pk(match_id)
    keys = [
        {"PK": pk, "SK": i["SK"]}
        for prefix in ("EVT#", "CORR#")
        for i in _query_all(None, "PK", pk, sk_prefix=prefix)
    ]
    with table().batch_writer() as batch:
        for k in keys:
            batch.delete_item(Key=k)
    return len(keys)


def write_projection(doc: dict[str, Any], expected_version: int | None) -> int:
    """Write a rebuilt match document, conditional on the version we read.

    Two projectors racing on the same match cannot interleave: the loser's
    write fails, it re-reads the log, and projects again.
    """
    new_version = int(doc.get("version") or 0)
    items = document_items(doc)
    state_item = next(i for i in items if i["SK"] == K.STATE)
    cond = (
        Attr("version").not_exists()
        if expected_version is None
        else Attr("version").eq(expected_version)
    )
    try:
        table().put_item(Item=state_item, ConditionExpression=cond)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise VersionConflict(doc["id"]) from exc
        raise
    with table().batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
        for item in items:
            if item["SK"] != K.STATE:
                batch.put_item(Item=item)
    return new_version


def state_version(match_id: str) -> int | None:
    resp = table().get_item(
        Key={"PK": K.match_pk(match_id), "SK": K.STATE}, ProjectionExpression="version"
    )
    item = resp.get("Item")
    return int(item["version"]) if item and "version" in item else None


# ---------------------------------------------------------------------------
# catalog: competitions, tables, teams, players, search
# ---------------------------------------------------------------------------


def put_catalog(kind: str, key: str, body: Any) -> None:
    table().put_item(Item={"PK": K.CATALOG_PK, "SK": f"{kind}#{key}", "body": pack(body)})


def get_catalog(kind: str, key: str) -> Any:
    resp = table().get_item(Key={"PK": K.CATALOG_PK, "SK": f"{kind}#{key}"})
    item = resp.get("Item")
    return unpack(item["body"]) if item else None


def put_tables(competition_id: str, season_id: str, tables: Sequence[dict[str, Any]]) -> None:
    pk = K.comp_season(competition_id, season_id)
    with table().batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
        for t in tables:
            batch.put_item(Item={"PK": pk, "SK": f"{K.TABLE_PREFIX}{t['group']}", "body": pack(t)})


def get_tables(competition_id: str, season_id: str) -> list[dict[str, Any]]:
    return [
        unpack(i["body"])
        for i in _query_all(
            None, "PK", K.comp_season(competition_id, season_id), sk_prefix=K.TABLE_PREFIX
        )
    ]


def put_entities(kind: str, entities: Iterable[dict[str, Any]]) -> int:
    """Teams and players: PK=TEAM#id|PLAYER#id, SK=META."""
    pk_fn = K.team_pk if kind == "team" else K.player_pk
    n = 0
    with table().batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
        for ent in entities:
            batch.put_item(Item={"PK": pk_fn(ent["id"]), "SK": K.META, "body": pack(ent)})
            n += 1
    return n


def get_entity(kind: str, entity_id: str) -> dict[str, Any] | None:
    pk_fn = K.team_pk if kind == "team" else K.player_pk
    resp = table().get_item(Key={"PK": pk_fn(entity_id), "SK": K.META})
    item = resp.get("Item")
    return unpack(item["body"]) if item else None


def put_alias(
    feed: str,
    feed_id: str,
    entity_type: str,
    canonical_id: str,
    confidence: float,
    needs_review: bool = False,
) -> None:
    table().put_item(
        Item={
            "PK": K.alias_pk(feed, feed_id),
            "SK": "ENTITY",
            "entity_type": entity_type,
            "canonical_id": canonical_id,
            "confidence": str(round(confidence, 3)),
            "needs_review": needs_review,
            **({"GSI1PK": "UNRESOLVED", "GSI1SK": f"{feed}#{feed_id}"} if needs_review else {}),
        }
    )


def get_alias(feed: str, feed_id: str) -> dict[str, Any] | None:
    resp = table().get_item(Key={"PK": K.alias_pk(feed, feed_id), "SK": "ENTITY"})
    return resp.get("Item")


def unresolved_aliases() -> list[dict[str, Any]]:
    return [
        {k: v for k, v in i.items() if k in ("PK", "entity_type", "canonical_id", "confidence")}
        for i in _query_all("GSI1", "GSI1PK", "UNRESOLVED")
    ]


def delete_match(match_id: str) -> int:
    """Delete every item under a match. Used only for replay ids (`live-*`),
    whose history is re-created on each replay; archived matches are never
    deleted."""
    if not match_id.startswith("live-"):
        raise ValueError("only replay matches can be deleted")
    pk = K.match_pk(match_id)
    keys = [{"PK": pk, "SK": i["SK"]} for i in _query_all(None, "PK", pk)]
    with table().batch_writer() as batch:
        for k in keys:
            batch.delete_item(Key=k)
    return len(keys)


def append_batch(events: Sequence[CanonicalEvent], corrections: Sequence[Correction]) -> None:
    """Append many records in BatchWriteItem calls of 25.

    Safe without a condition *because* the caller is the single writer for the
    match (it holds the shard lease) and keys are deterministic: writing an
    event whose key already exists writes the identical item again, which
    changes nothing. The per-item conditional path, `append_event`, remains for
    writers that are not partition owners.
    """
    with table().batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
        for e in events:
            batch.put_item(
                Item={
                    "PK": K.match_pk(e.match_id),
                    "SK": K.event_sk(e.index, e.event_id),
                    "body": pack(event_to_dict(e)),
                    "received_at": int(time.time() * 1000),
                }
            )
        for c in corrections:
            batch.put_item(
                Item={
                    "PK": K.match_pk(c.match_id),
                    "SK": K.correction_sk(c.decided_at_minute, c.period, c.correction_id),
                    "body": pack(correction_to_dict(c)),
                }
            )
