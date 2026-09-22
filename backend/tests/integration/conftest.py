"""Integration fixtures: a real DynamoDB API (moto, in-process) and a real
Redis API (fakeredis), wired in by overriding the same seams production uses -
configuration and the client factories. No network, no Docker, so these run
in CI on every push.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from typing import Any

import fakeredis
import pytest

from onside import config
from onside.store import client as store_client
from onside.store import kv as kv_store
from onside.streams import bus

SAMPLE_MATCHES = 12


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from moto import mock_aws

    monkeypatch.setenv("ONSIDE_ENV", "test-moto")  # not "local": no endpoint override
    monkeypatch.setenv("ONSIDE_TABLE", "onside-test")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    config.settings.cache_clear()
    store_client.resource.cache_clear()
    with mock_aws():
        store_client.create_table()
        yield
    config.settings.cache_clear()
    store_client.resource.cache_clear()


@pytest.fixture
def redis_fake(monkeypatch: pytest.MonkeyPatch) -> fakeredis.FakeRedis:
    server = fakeredis.FakeServer()
    r = fakeredis.FakeRedis(server=server, decode_responses=True)
    bus.sync_client.cache_clear()
    monkeypatch.setattr(bus, "sync_client", lambda: r)
    monkeypatch.setattr(bus, "async_client",
                        lambda: fakeredis.aioredis.FakeRedis(server=server, decode_responses=True))
    return r


@pytest.fixture
def sample_docs() -> list[dict]:
    """A handful of real match documents from the built archive, including the
    2022 final."""
    docs_dir = config.ROOT / "data" / "processed" / "matches"
    paths = sorted(docs_dir.glob("*.json.gz"))[:SAMPLE_MATCHES]
    final = docs_dir / "3869685.json.gz"
    if final.exists() and final not in paths:
        paths.append(final)
    if not paths:
        pytest.skip("No built match documents; run onside.ingest.build")
    out = []
    for p in paths:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            out.append(json.load(f))
    return out


# ---------------------------------------------------------------- the key-value store
# Redis everywhere except the free-tier AWS deployment, which keeps the same
# keys in DynamoDB (store/kv.py). Tests taking `kv` run once on each.

KV_TABLE = "onside-kv-test"


@pytest.fixture
def dynamo_kv(monkeypatch: pytest.MonkeyPatch) -> Iterator[kv_store.DynamoKV]:
    from moto import mock_aws

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("ONSIDE_ENV", "test-moto")  # not "local": no endpoint override
    config.settings.cache_clear()
    with mock_aws():
        kv_store.create_table(KV_TABLE)
        yield kv_store.DynamoKV(table=KV_TABLE)
    config.settings.cache_clear()


@pytest.fixture(params=["redis", "dynamo"])
def kv(request: pytest.FixtureRequest) -> Any:
    if request.param == "redis":
        return fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    return request.getfixturevalue("dynamo_kv")
