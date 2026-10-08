"""The Lambda entry point: secrets from Parameter Store, and scheduled jobs
arriving as HTTP requests from the Lambda Web Adapter."""

from __future__ import annotations

import json

import fakeredis
import pytest
from fastapi.testclient import TestClient

from onside import config, serverless
from onside.streams import bus
from onside.workers import fixtures


class FakeSSM:
    """get_parameters_by_path decrypts (and costs a KMS request each);
    describe_parameters only says what version each one is on."""

    def __init__(self, params):
        self.params, self.asked = params, []
        self.op = ""

    def get_paginator(self, name):
        self.op = name
        return self

    def paginate(self, **kw):
        self.asked.append({"op": self.op, **kw})
        if self.op == "describe_parameters":
            yield {"Parameters": [{"Name": p["Name"], "Version": p.get("Version", 1)}
                                  for p in self.params]}
        else:
            yield {"Parameters": self.params[:1]}
            yield {"Parameters": self.params[1:]}

    def decrypts(self):
        return sum(1 for a in self.asked if a["op"] == "get_parameters_by_path")


def test_secrets_are_read_by_path_decrypted_and_named_like_env_vars(monkeypatch):
    monkeypatch.delenv("FOOTBALL_DATA_API_KEY", raising=False)
    monkeypatch.delenv("BLUESKY_APP_PASSWORD", raising=False)
    ssm = FakeSSM([
        {"Name": "/onside/FOOTBALL_DATA_API_KEY", "Value": "k1"},
        {"Name": "/onside/BLUESKY_APP_PASSWORD", "Value": "p1"},
    ])
    names = serverless.load_ssm("/onside/", client=ssm)
    assert names == ["BLUESKY_APP_PASSWORD", "FOOTBALL_DATA_API_KEY"]  # names only, never values
    assert ssm.asked == [
        {"op": "get_parameters_by_path", "Path": "/onside", "WithDecryption": True,
         "Recursive": False}
    ]
    import os

    assert os.environ["FOOTBALL_DATA_API_KEY"] == "k1"


def test_no_path_means_no_call():
    assert serverless.load_ssm("", client=None) == []
    assert serverless.versions("", client=None) == []


def test_versions_are_read_without_decrypting_anything():
    ssm = FakeSSM([
        {"Name": "/onside/FOOTBALL_DATA_API_KEY", "Value": "k1", "Version": 3},
        {"Name": "/onside/BLUESKY_APP_PASSWORD", "Value": "p1", "Version": 1},
    ])
    assert serverless.versions("/onside", client=ssm) == [
        ("BLUESKY_APP_PASSWORD", 1),
        ("FOOTBALL_DATA_API_KEY", 3),
    ]
    assert ssm.decrypts() == 0  # a KMS request each, and nothing changed


@pytest.fixture
def worker(monkeypatch):
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(bus, "sync_client", lambda: r)
    monkeypatch.delenv("FOOTBALL_DATA_API_KEY", raising=False)
    config.settings.cache_clear()
    yield TestClient(serverless.worker_app()), r
    config.settings.cache_clear()


def test_a_scheduled_job_runs_and_reports(worker):
    client, r = worker
    res = client.post("/events", json={"job": "fixtures"})
    assert res.status_code == 200 and res.json()["result"] == {"enabled": False}
    assert json.loads(r.get(fixtures.KEY))["enabled"] is False  # the site says fixtures are off


def test_an_unknown_job_is_refused(worker):
    client, _ = worker
    assert client.post("/events", json={"job": "mine-bitcoin"}).status_code == 400
    assert client.get("/health").json() == {"ok": True}


def test_a_rotated_key_is_picked_up_without_a_redeploy(monkeypatch):
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(bus, "sync_client", lambda: r)
    monkeypatch.setenv("ONSIDE_SSM_PATH", "/onside")
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "old")  # so the test's changes are undone after
    values = {"FOOTBALL_DATA_API_KEY": "old"}

    version = {"n": 1}
    reads = {"n": 0}

    def fake_load(path=None, client=None):
        import os

        reads["n"] += 1
        for k, v in values.items():
            os.environ[k] = v
        serverless._loaded[:] = sorted(values)
        return sorted(values)

    monkeypatch.setattr(serverless, "load_ssm", fake_load)
    monkeypatch.setattr(serverless, "versions",
                        lambda path=None, client=None: [("FOOTBALL_DATA_API_KEY", version["n"])])
    fake_load()
    config.settings.cache_clear()
    app = serverless.worker_app()
    client = TestClient(app)
    seen = []
    monkeypatch.setattr("onside.workers.fixtures.Poller.tick",
                        lambda self: seen.append(config.settings().football_data_key) or {"ok": True, "matches": []})
    client.post("/events", json={"job": "fixtures"})
    monkeypatch.setattr(serverless, "SECRETS_EVERY_S", 0)

    before = reads["n"]
    client.post("/events", json={"job": "fixtures"})  # nothing rotated
    assert reads["n"] == before  # so nothing was decrypted

    values["FOOTBALL_DATA_API_KEY"] = "new"
    version["n"] = 2  # the rotation bumps the parameter's version
    client.post("/events", json={"job": "fixtures"})
    assert reads["n"] == before + 1
    assert seen == ["old", "old", "new"]
    config.settings.cache_clear()
