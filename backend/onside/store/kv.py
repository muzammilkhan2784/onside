"""The slice of Redis Onside needs, on a DynamoDB table.

The free-tier AWS deployment has no Redis: ElastiCache is the one piece of the
production stack with no free tier. The fixtures and social workers and the
API routes that read them only use a handful of Redis commands, so this class
implements exactly those - same names, same arguments, same return shapes as
redis-py with `decode_responses=True` - and they run unchanged against it.

    table "onside-kv" (PK = key, SK = what)

    string        SK "~"                  v (or b: gzip, when large), exp
    hash field    SK "h#<field>"          v
    set member    SK "s#<member>"
    zset member   SK "z#<score>#<member>" (scores fixed-width, so SK order is score order)
    counter       SK "~"                  n (a number, so INCR is one atomic ADD)

`exp` is a Unix time; DynamoDB's TTL deletes expired items eventually, and
reads treat them as gone straight away. Two deliberate limits, both true of
every caller: a sorted-set member keeps the score it was first added with, and
EXISTS/GET/SET address string keys only. Streams and pub/sub are not here at
all: replays and WebSockets need the full deployment.
"""

from __future__ import annotations

import gzip
import os
import time
from collections.abc import Iterable, Iterator
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.config import Config

from ..config import settings

STRING = "~"
TOP = chr(0xFFFF)  # sorts after every character a key can contain
#: Values larger than this are stored gzipped. A write costs a unit per KB,
#: and the fixtures snapshot - 50 KB of JSON rewritten every minute - shrinks
#: about tenfold.
COMPRESS_OVER = 4096


def _score(value: float | int | str) -> str:
    """A score as a fixed-width string whose text order is its number order.
    Covers 0 to 1e13 - timestamps and counts, which is all Onside stores."""
    return f"{float(value):024.6f}"


def _bound(value: float | int | str, *, upper: bool) -> str:
    """A ZRANGEBYSCORE bound ("-inf", "+inf", "(123.4" exclusive, 123.4) as an SK bound."""
    v = str(value)
    if v in ("-inf", "+inf", "inf"):
        return "z#" + (TOP if v != "-inf" else "")
    exclusive = v.startswith("(")
    s = _score(v.lstrip("("))
    if upper:
        # "z#<s>" sorts before every "z#<s>#member", so it excludes that score;
        # "z#<s>#<TOP>" sorts after them all, so it includes it.
        return f"z#{s}" if exclusive else f"z#{s}#{TOP}"
    return f"z#{s}#{TOP}" if exclusive else f"z#{s}"


def _resource() -> Any:
    s = settings()
    kwargs: dict[str, Any] = {
        "region_name": s.region,
        # The table runs on the always-free provisioned capacity; a burst is
        # absorbed by retrying with backoff, not by paying for more.
        "config": Config(retries={"max_attempts": 10, "mode": "adaptive"}),
    }
    if s.is_local:  # DynamoDB Local, as store/client.py does
        kwargs["endpoint_url"] = s.dynamo_endpoint
        kwargs["aws_access_key_id"] = os.environ.get("AWS_ACCESS_KEY_ID", "onside")
        kwargs["aws_secret_access_key"] = os.environ.get(
            "AWS_SECRET_ACCESS_KEY", "onside-local-only"
        )
    return boto3.resource("dynamodb", **kwargs)


def create_table(name: str | None = None, resource: Any = None) -> bool:
    """For tests and local runs of the free-tier profile; in AWS the OnsideFree
    stack owns the table. Returns True if it was created."""
    client = (resource or _resource()).meta.client
    name = name or settings().kv_table
    if name in client.list_tables()["TableNames"]:
        return False
    client.create_table(
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
    )
    client.get_waiter("table_exists").wait(TableName=name)
    return True


class DynamoKV:
    def __init__(self, table: str | None = None, resource: Any = None) -> None:
        self.resource = resource or _resource()
        self.table = self.resource.Table(table or settings().kv_table)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _live(item: dict[str, Any] | None) -> bool:
        return bool(item) and not (item.get("exp") and float(item["exp"]) < time.time())  # type: ignore[union-attr]

    @staticmethod
    def _value(item: dict[str, Any]) -> str:
        if "n" in item:
            return str(int(item["n"]))
        if "b" in item:
            blob = item["b"]
            return gzip.decompress(bytes(getattr(blob, "value", blob))).decode("utf-8")
        return str(item.get("v", ""))

    def _query(
        self, key: str, lo: str, hi: str, *, forward: bool = True, count: bool = False
    ) -> Iterator[Any]:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("PK").eq(key) & Key("SK").between(lo, hi),
            "ScanIndexForward": forward,
        }
        if count:
            kwargs["Select"] = "COUNT"
        while True:
            page = self.table.query(**kwargs)
            if count:
                yield page["Count"]
            else:
                yield from page["Items"]
            if "LastEvaluatedKey" not in page:
                return
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def _delete(self, keys: Iterable[tuple[str, str]]) -> int:
        n = 0
        with self.table.batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
            for pk, sk in keys:
                batch.delete_item(Key={"PK": pk, "SK": sk})
                n += 1
        return n

    # ---------------------------------------------------------------- strings
    def ping(self) -> bool:
        self.table.load()
        return True

    def get(self, key: str) -> str | None:
        item = self.table.get_item(Key={"PK": key, "SK": STRING}).get("Item")
        return self._value(item) if self._live(item) else None

    def set(self, key: str, value: Any, ex: int | None = None, nx: bool = False) -> bool:
        text = str(value)
        item: dict[str, Any] = {"PK": key, "SK": STRING}
        if len(text) > COMPRESS_OVER:
            item["b"] = gzip.compress(text.encode("utf-8"), compresslevel=6)
        else:
            item["v"] = text
        if ex:
            item["exp"] = int(time.time() + ex)
        if not nx:
            self.table.put_item(Item=item)
            return True
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression=Attr("PK").not_exists() | Attr("exp").lt(int(time.time())),
            )
            return True
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def exists(self, *keys: str) -> int:
        return sum(1 for k in keys if self.get(k) is not None)

    def mget(self, keys: list[str]) -> list[str | None]:
        found: dict[str, str] = {}
        name = self.table.name
        unique = list(dict.fromkeys(keys))
        for i in range(0, len(unique), 100):
            request: dict[str, Any] = {
                name: {"Keys": [{"PK": k, "SK": STRING} for k in unique[i : i + 100]]}
            }
            while request:
                resp = self.resource.batch_get_item(RequestItems=request)
                for item in resp["Responses"].get(name, []):
                    if self._live(item):
                        found[item["PK"]] = self._value(item)
                request = resp.get("UnprocessedKeys") or {}
        return [found.get(k) for k in keys]

    def incrby(self, key: str, amount: int = 1) -> int:
        resp = self.table.update_item(
            Key={"PK": key, "SK": STRING},
            UpdateExpression="ADD n :a",
            ExpressionAttributeValues={":a": amount},
            ReturnValues="UPDATED_NEW",
        )
        return int(resp["Attributes"]["n"])

    def incr(self, key: str) -> int:
        return self.incrby(key, 1)

    def expire(self, key: str, seconds: int) -> bool:
        self.table.update_item(
            Key={"PK": key, "SK": STRING},
            UpdateExpression="SET #e = :e",
            ExpressionAttributeNames={"#e": "exp"},
            ExpressionAttributeValues={":e": int(time.time() + seconds)},
        )
        return True

    # ---------------------------------------------------------------- hashes
    def hset(
        self,
        name: str,
        key: str | None = None,
        value: Any = None,
        mapping: dict[str, Any] | None = None,
    ) -> int:
        fields = dict(mapping or {})
        if key is not None:
            fields[key] = value
        with self.table.batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
            for f, v in fields.items():
                batch.put_item(Item={"PK": name, "SK": f"h#{f}", "v": str(v)})
        return len(fields)

    def hget(self, name: str, key: str) -> str | None:
        item = self.table.get_item(Key={"PK": name, "SK": f"h#{key}"}).get("Item")
        return str(item["v"]) if item else None

    def hgetall(self, name: str) -> dict[str, str]:
        return {i["SK"][2:]: str(i["v"]) for i in self._query(name, "h#", f"h#{TOP}")}

    # ---------------------------------------------------------------- sets
    def sadd(self, name: str, *members: str) -> int:
        with self.table.batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
            for m in members:
                batch.put_item(Item={"PK": name, "SK": f"s#{m}"})
        return len(members)

    def srem(self, name: str, *members: str) -> int:
        return self._delete((name, f"s#{m}") for m in members)

    def smembers(self, name: str) -> set[str]:
        return {i["SK"][2:] for i in self._query(name, "s#", f"s#{TOP}")}

    # ---------------------------------------------------------------- sorted sets
    def zadd(self, name: str, mapping: dict[str, float]) -> int:
        with self.table.batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
            for member, score in mapping.items():
                batch.put_item(Item={"PK": name, "SK": f"z#{_score(score)}#{member}"})
        return len(mapping)

    @staticmethod
    def _member(sk: str) -> tuple[str, float]:
        _, score, member = sk.split("#", 2)
        return member, float(score)

    def zrevrangebyscore(
        self,
        name: str,
        max: Any,  # noqa: A002 - redis-py's parameter names
        min: Any,  # noqa: A002
        start: int | None = None,
        num: int | None = None,
        withscores: bool = False,
    ) -> list[Any]:
        lo, hi = _bound(min, upper=False), _bound(max, upper=True)
        out: list[Any] = []
        skip, want = start or 0, num
        for item in self._query(name, lo, hi, forward=False):
            if skip:
                skip -= 1
                continue
            member, score = self._member(item["SK"])
            out.append((member, score) if withscores else member)
            if want is not None and len(out) >= want:
                break
        return out

    def zcount(self, name: str, min: Any, max: Any) -> int:  # noqa: A002
        return sum(self._query(name, _bound(min, upper=False), _bound(max, upper=True), count=True))

    def zremrangebyscore(self, name: str, min: Any, max: Any) -> int:  # noqa: A002
        items = self._query(name, _bound(min, upper=False), _bound(max, upper=True))
        return self._delete((name, i["SK"]) for i in items)

    def zremrangebyrank(self, name: str, start: int, stop: int) -> int:
        """Only the form Onside uses: (0, -keep-1) - drop all but the newest `keep`."""
        if start != 0 or stop >= 0:
            raise NotImplementedError("zremrangebyrank supports only (0, -keep-1)")
        keep = -stop - 1
        newest_first = self._query(name, "z#", f"z#{TOP}", forward=False)
        return self._delete((name, i["SK"]) for n, i in enumerate(newest_first) if n >= keep)

    # ---------------------------------------------------------------- pipelines
    def pipeline(self, transaction: bool = False) -> _Pipeline:
        return _Pipeline(self)


class _Pipeline:
    """Queues calls and runs them in order on execute(). Not atomic - neither
    is a Redis pipeline with transaction=False, which is how Onside uses it."""

    def __init__(self, kv: DynamoKV) -> None:
        self.kv = kv
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        def queue(*args: Any, **kwargs: Any) -> _Pipeline:
            self.calls.append((name, args, kwargs))
            return self

        return queue

    def execute(self) -> list[Any]:
        calls, self.calls = self.calls, []
        return [getattr(self.kv, n)(*a, **k) for n, a, k in calls]
