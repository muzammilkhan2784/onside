"""DynamoDB connection and table lifecycle.

One table, on-demand billing, two GSIs projecting ALL. The same code talks to
DynamoDB Local in development and to AWS in production; only the endpoint
differs, and it comes from configuration.
"""

from __future__ import annotations

import gzip
import json
import os
import time
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from ..config import settings

GSIS = ("GSI1", "GSI2")


@lru_cache(maxsize=1)
def resource() -> Any:
    s = settings()
    kwargs: dict[str, Any] = {
        "region_name": s.region,
        "config": Config(retries={"max_attempts": 8, "mode": "adaptive"}, max_pool_connections=64),
    }
    if s.is_local:
        # DynamoDB Local accepts any credentials but boto3 insists on some.
        # In AWS the task role supplies real ones and this branch never runs.
        kwargs["endpoint_url"] = s.dynamo_endpoint
        kwargs["aws_access_key_id"] = os.environ.get("AWS_ACCESS_KEY_ID", "onside")
        kwargs["aws_secret_access_key"] = os.environ.get(
            "AWS_SECRET_ACCESS_KEY", "onside-local-only"
        )
    return boto3.resource("dynamodb", **kwargs)


def table() -> Any:
    return resource().Table(settings().table)


def create_table(wait: bool = True) -> bool:
    """Create the table if it does not exist. Returns True if it was created."""
    client = resource().meta.client
    name = settings().table
    try:
        client.describe_table(TableName=name)
        return False
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    attrs = [
        {"AttributeName": n, "AttributeType": "S"}
        for n in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")
    ]
    client.create_table(
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=attrs,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": g,
                "KeySchema": [
                    {"AttributeName": f"{g}PK", "KeyType": "HASH"},
                    {"AttributeName": f"{g}SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for g in GSIS
        ],
    )
    if wait:
        client.get_waiter("table_exists").wait(TableName=name)
    return True


def delete_table() -> None:
    client = resource().meta.client
    try:
        client.delete_table(TableName=settings().table)
        client.get_waiter("table_not_exists").wait(TableName=settings().table)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise


def wait_until_ready(timeout: float = 60.0) -> None:
    """Block until DynamoDB answers. Compose starts services in parallel."""
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            resource().meta.client.list_tables(Limit=1)
            return
        except Exception as exc:  # noqa: BLE001 - any failure means not ready yet
            last = exc
            time.sleep(1)
    raise RuntimeError(f"DynamoDB at {settings().dynamo_endpoint} did not become ready: {last}")


# ---------------------------------------------------------------------------
# document bodies
# ---------------------------------------------------------------------------
# Large JSON documents are stored gzipped in a binary attribute rather than as
# native DynamoDB maps: it avoids the float->Decimal conversion on every read,
# cuts item size (and so read cost) by roughly 5x, and nothing ever queries
# inside these bodies - the attributes that are filtered on are promoted to
# top-level scalars on the item.


def pack(obj: Any) -> bytes:
    return gzip.compress(json.dumps(obj, separators=(",", ":")).encode("utf-8"), compresslevel=6)


def unpack(blob: Any) -> Any:
    raw = blob.value if hasattr(blob, "value") else blob
    return json.loads(gzip.decompress(bytes(raw)).decode("utf-8"))
