"""infra/free_check.py: the answer to "is this account still free?".

It runs against a stand-in AWS, because the point of the tool is what it says
about an account, and that has to be right without one.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "infra"))

free_check = pytest.importorskip("free_check")


class FakeClient:
    """Answers the calls free_check makes; raises for anything else, as a
    missing permission would."""

    def __init__(self, service: str, data: dict):
        self.service, self.data = service, data
        self.calls: list[tuple[str, dict]] = []

    def __getattr__(self, name: str):
        def call(**kwargs):
            self.calls.append((name, kwargs))
            key = f"{self.service}.{name}"
            if key not in self.data:
                raise RuntimeError(f"no permission for {key}")
            value = self.data[key]
            return value(**kwargs) if callable(value) else value

        return call

    def get_paginator(self, op: str):
        client = self

        class P:
            def paginate(self, **kwargs):
                yield getattr(client, op)(**kwargs)

        return P()


def fake_aws(data: dict):
    made: dict[str, FakeClient] = {}

    def client(service: str) -> FakeClient:
        return made.setdefault(service, FakeClient(service, data))

    return client, made


EMPTY = {
    "ec2.describe_instances": {"Reservations": []},
    "ec2.describe_nat_gateways": {"NatGateways": []},
    "ec2.describe_addresses": {"Addresses": []},
    "ec2.describe_volumes": {"Volumes": []},
    "ec2.describe_vpc_endpoints": {"VpcEndpoints": []},
    "elbv2.describe_load_balancers": {"LoadBalancers": []},
    "elasticache.describe_cache_clusters": {"CacheClusters": []},
    "rds.describe_db_instances": {"DBInstances": []},
    "ecs.list_clusters": {"clusterArns": []},
    "ecs.describe_clusters": {"clusters": []},
    "eks.list_clusters": {"clusters": []},
    "opensearch.list_domain_names": {"DomainNames": []},
    "redshift.describe_clusters": {"Clusters": []},
    "route53.list_hosted_zones": {"HostedZones": []},
    "dynamodb.list_tables": {"TableNames": ["onside-free", "onside-free-kv"]},
    "dynamodb.describe_table": lambda TableName: {
        "Table": {
            "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"},
            "TableSizeBytes": 80_000_000,
        }
        if TableName == "onside-free"
        else {
            "BillingModeSummary": {"BillingMode": "PROVISIONED"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 20, "WriteCapacityUnits": 20},
            "TableSizeBytes": 3_000_000,
        }
    },
    "ecr.describe_repositories": {"repositories": [{"repositoryName": "cdk-assets"}]},
    "ecr.describe_images": {
        "imageDetails": [{"imageSizeInBytes": 500_000_000} for _ in range(4)]
    },
    "ecr.get_lifecycle_policy": RuntimeError,  # no policy yet: the call fails
    "ecr.put_lifecycle_policy": {"repositoryName": "cdk-assets"},
    "logs.put_retention_policy": {},
    "logs.describe_log_groups": {
        "logGroups": [
            {"logGroupName": "/aws/lambda/onside-free-api"},  # no retention
            {"logGroupName": "/aws/lambda/onside-free-worker", "retentionInDays": 3},
            {"logGroupName": "/aws/someone-else"},
        ]
    },
    "freetier.get_free_tier_usage": {
        "freeTierUsages": [
            {"service": "Lambda", "description": "400,000 GB-seconds", "actualUsageAmount": 160_000, "limit": 400_000},
            {"service": "DynamoDB", "description": "25 GB storage", "actualUsageAmount": 0.08, "limit": 25},
        ]
    },
}


def run(data: dict, apply: bool = False) -> tuple[int, str, dict]:
    client, made = fake_aws(data)
    out = io.StringIO()
    code = free_check.report(client, apply=apply, out=out)
    return code, out.getvalue(), made


def test_a_free_account_says_so_and_exits_clean():
    code, text, _ = run(EMPTY)
    assert code == 0
    assert "Nothing here is billed by the hour." in text
    assert "onside-free-kv: provisioned 20/20" in text
    assert "20 read, 20 write (free allowance 25/25)" in text
    assert "160,000" not in text and " 40%  Lambda" in text  # shown as a percentage


def test_anything_billed_by_the_hour_is_named_and_fails():
    costly = {
        **EMPTY,
        "elasticache.describe_cache_clusters": {"CacheClusters": [{"CacheClusterId": "redis"}]},
        "ec2.describe_nat_gateways": {"NatGateways": [{"State": "available"}]},
        "ec2.describe_volumes": {"Volumes": [{"State": "available"}, {"State": "in-use"}]},
    }
    code, text, _ = run(costly)
    assert code == 1
    assert "1 x ElastiCache (Redis) nodes" in text
    assert "1 x NAT gateways" in text
    assert "1 x Unattached disks (EBS)" in text  # the in-use one is not flagged
    assert "Something here is billed by the hour" in text


def test_a_missing_permission_is_not_a_crash():
    code, text, _ = run({"dynamodb.list_tables": {"TableNames": []}})
    assert code == 0 and "nothing:" in text


def test_fix_expires_old_images_and_bounds_only_our_logs():
    code, text, made = run(EMPTY, apply=True)
    assert code == 0
    ecr_calls = [c for c in made["ecr"].calls if c[0] == "put_lifecycle_policy"]
    assert len(ecr_calls) == 1
    policy = json.loads(ecr_calls[0][1]["lifecyclePolicyText"])
    assert policy["rules"][0]["selection"]["countNumber"] == free_check.KEEP_IMAGES
    assert policy["rules"][0]["action"] == {"type": "expire"}
    kept = [c[1]["logGroupName"] for c in made["logs"].calls if c[0] == "put_retention_policy"]
    assert kept == ["/aws/lambda/onside-free-api"]  # not the other account's group
    assert "keeping the 2 newest images" in text
