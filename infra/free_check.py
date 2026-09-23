#!/usr/bin/env python3
"""Is this AWS account still free? Read-only, and it says what it found.

    python free_check.py            look, report, and exit 1 if something is
                                    billed by the hour
    python free_check.py --fix      also trim what quietly accumulates: keep
                                    the two newest container images, and put a
                                    retention on Onside's log groups

Onside's free deployment uses CloudFront, Lambda, DynamoDB, EventBridge, SSM
and S3, all inside allowances that do not expire. Three things can still cost
a little: stored container images, requests against the on-demand table, and
logs kept forever. Everything this checks for - an ElastiCache node, a NAT
gateway, a load balancer, an idle EC2 instance, an unattached disk - is billed
by the hour whether or not anyone visits the site.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

import boto3

#: Keep two: the live image and the one before it, to roll back to.
KEEP_IMAGES = 2
LIFECYCLE = {
    "rules": [
        {
            "rulePriority": 1,
            "description": f"Onside: keep the {KEEP_IMAGES} newest images",
            "selection": {
                "tagStatus": "any",
                "countType": "imageCountMoreThan",
                "countNumber": KEEP_IMAGES,
            },
            "action": {"type": "expire"},
        }
    ]
}
LOG_RETENTION_DAYS = 3
Client = Callable[[str], Any]


def safe(call: Callable[[], Any], default: Any) -> Any:
    """AWS answers, or it does not - a missing permission is not a crash."""
    try:
        return call()
    except Exception:  # noqa: BLE001 - a refusal is an answer: "cannot see it"
        return default


def _pages(client: Any, op: str, key: str, **kwargs: Any) -> list[Any]:
    out: list[Any] = []
    try:
        for page in client.get_paginator(op).paginate(**kwargs):
            out.extend(page.get(key, []))
    except Exception:  # noqa: BLE001 - same: report what was visible
        return out
    return out


def hourly_resources(client: Client) -> list[tuple[str, int, str]]:
    """Anything that charges while it exists. Every count should be zero."""
    ec2 = client("ec2")
    instances = [
        i
        for r in safe(lambda: ec2.describe_instances()["Reservations"], [])
        for i in r.get("Instances", [])
        if i.get("State", {}).get("Name") == "running"
    ]
    found = [
        ("EC2 instances running", len(instances), "billed per hour"),
        (
            "NAT gateways",
            len([
                n
                for n in safe(lambda: ec2.describe_nat_gateways()["NatGateways"], [])
                if n.get("State") == "available"
            ]),
            "about $32 a month each",
        ),
        (
            "Unattached Elastic IPs",
            len([a for a in safe(lambda: ec2.describe_addresses()["Addresses"], []) if not a.get("AssociationId")]),
            "charged when not in use",
        ),
        (
            "Unattached disks (EBS)",
            len([
                v
                for v in safe(lambda: ec2.describe_volumes()["Volumes"], [])
                if v.get("State") == "available"
            ]),
            "billed per GB-month",
        ),
        (
            "Interface VPC endpoints",
            len(safe(lambda: ec2.describe_vpc_endpoints()["VpcEndpoints"], [])),
            "billed per hour",
        ),
        (
            "Load balancers",
            len(_pages(client("elbv2"), "describe_load_balancers", "LoadBalancers")),
            "about $18 a month each",
        ),
        (
            "ElastiCache (Redis) nodes",
            len(safe(lambda: client("elasticache").describe_cache_clusters()["CacheClusters"], [])),
            "no free tier - the reason this deployment has no Redis",
        ),
        (
            "RDS databases",
            len(_pages(client("rds"), "describe_db_instances", "DBInstances")),
            "billed per hour",
        ),
        (
            "ECS tasks running",
            sum(
                c.get("runningTasksCount", 0)
                for c in safe(
                    lambda: client("ecs").describe_clusters(
                        clusters=safe(lambda: client("ecs").list_clusters()["clusterArns"], []),
                        include=["STATISTICS"],
                    )["clusters"],
                    [],
                )
            ),
            "Fargate is billed per second of task time",
        ),
        (
            "EKS clusters",
            len(safe(lambda: client("eks").list_clusters()["clusters"], [])),
            "about $73 a month each",
        ),
        (
            "OpenSearch domains",
            len(safe(lambda: client("opensearch").list_domain_names()["DomainNames"], [])),
            "billed per hour",
        ),
        (
            "Redshift clusters",
            len(safe(lambda: client("redshift").describe_clusters()["Clusters"], [])),
            "billed per hour",
        ),
        (
            "Route 53 hosted zones",
            len(_pages(client("route53"), "list_hosted_zones", "HostedZones")),
            "$0.50 a month each",
        ),
    ]
    return [row for row in found if row[1]]


def dynamo_capacity(client: Client) -> dict[str, Any]:
    """Provisioned tables share an always-free 25 read and 25 write units."""
    ddb = client("dynamodb")
    tables = _pages(ddb, "list_tables", "TableNames")
    rows, read, write = [], 0, 0
    for name in tables:
        d = safe(lambda n=name: ddb.describe_table(TableName=n)["Table"], None)
        if not d:
            continue
        mode = (d.get("BillingModeSummary") or {}).get("BillingMode", "PROVISIONED")
        thr = d.get("ProvisionedThroughput") or {}
        r, w = int(thr.get("ReadCapacityUnits", 0)), int(thr.get("WriteCapacityUnits", 0))
        read, write = read + r, write + w
        rows.append({
            "name": name,
            "mode": "on-demand" if mode == "PAY_PER_REQUEST" else f"provisioned {r}/{w}",
            "gb": round(d.get("TableSizeBytes", 0) / 1e9, 2),
        })
    return {"tables": rows, "read": read, "write": write, "free_read": 25, "free_write": 25}


def ecr_usage(client: Client) -> list[dict[str, Any]]:
    ecr = client("ecr")
    out = []
    for repo in _pages(ecr, "describe_repositories", "repositories"):
        name = repo["repositoryName"]
        images = _pages(ecr, "describe_images", "imageDetails", repositoryName=name)
        policy = safe(lambda n=name: ecr.get_lifecycle_policy(repositoryName=n), None)
        out.append({
            "name": name,
            "images": len(images),
            "gb": round(sum(i.get("imageSizeInBytes", 0) for i in images) / 1e9, 2),
            "expires_old": bool(policy),
        })
    return out


def unbounded_log_groups(client: Client) -> list[str]:
    return [
        g["logGroupName"]
        for g in _pages(client("logs"), "describe_log_groups", "logGroups")
        if not g.get("retentionInDays")
    ]


def free_tier_usage(client: Client, limit: int = 6) -> list[dict[str, Any]]:
    """What the always-free allowances have been used for this month."""
    rows = _pages(client("freetier"), "get_free_tier_usage", "freeTierUsages")
    used = []
    for r in rows:
        limit_v = r.get("limit") or 0
        pct = round(100 * (r.get("actualUsageAmount") or 0) / limit_v) if limit_v else 0
        used.append({
            "service": r.get("service", ""),
            "what": (r.get("description") or "")[:60],
            "percent": pct,
        })
    used.sort(key=lambda r: r["percent"], reverse=True)
    return used[:limit]


def fix(client: Client, repos: list[dict[str, Any]], groups: list[str]) -> list[str]:
    """The two charges that creep up on their own, with the creep removed."""
    done = []
    ecr = client("ecr")
    for repo in repos:
        if repo["expires_old"] or repo["images"] <= KEEP_IMAGES:
            continue
        if safe(
            lambda n=repo["name"]: ecr.put_lifecycle_policy(
                repositoryName=n, lifecyclePolicyText=json.dumps(LIFECYCLE)
            ),
            None,
        ):
            done.append(f"{repo['name']}: keeping the {KEEP_IMAGES} newest images")
    logs = client("logs")
    for name in groups:
        if not name.startswith("/aws/lambda/onside"):
            continue  # someone else's logs are not ours to shorten
        if safe(
            lambda n=name: logs.put_retention_policy(
                logGroupName=n, retentionInDays=LOG_RETENTION_DAYS
            ),
            None,
        ) is not None:
            done.append(f"{name}: keeping {LOG_RETENTION_DAYS} days of logs")
    return done


def report(client: Client, apply: bool = False, out: Any = sys.stdout) -> int:
    def say(line: str = "") -> None:
        print(line, file=out)

    hourly = hourly_resources(client)
    ddb = dynamo_capacity(client)
    repos = ecr_usage(client)
    groups = unbounded_log_groups(client)

    say("Billed by the hour")
    if hourly:
        for label, n, note in hourly:
            say(f"  {n} x {label} - {note}")
    else:
        say("  nothing: no instances, load balancers, NAT gateways, databases or Redis.")

    say()
    say("DynamoDB")
    for t in ddb["tables"]:
        say(f"  {t['name']}: {t['mode']}, {t['gb']} GB")
    say(
        f"  provisioned in total: {ddb['read']} read, {ddb['write']} write "
        f"(free allowance {ddb['free_read']}/{ddb['free_write']}); storage is free to 25 GB"
    )
    if ddb["read"] > ddb["free_read"] or ddb["write"] > ddb["free_write"]:
        say("  ! over the free capacity - the excess is charged")

    say()
    say("Stored container images (the one steady cost, about $0.10 a GB a month)")
    for r in repos:
        keep = "old ones expire" if r["expires_old"] else "keeps every version"
        say(f"  {r['name']}: {r['images']} images, {r['gb']} GB, {keep}")
    if not repos:
        say("  none")

    say()
    say("Logs kept forever")
    say(f"  {len(groups)} log groups with no retention" if groups else "  none")

    usage = free_tier_usage(client)
    if usage:
        say()
        say("Free allowances used this month")
        for u in usage:
            say(f"  {u['percent']:>3}%  {u['service']}: {u['what']}")

    if apply:
        say()
        say("Trimming")
        done = fix(client, repos, groups)
        for line in done:
            say(f"  {line}")
        if not done:
            say("  nothing to trim")

    say()
    say(
        "Something here is billed by the hour - see above."
        if hourly
        else "Nothing here is billed by the hour."
    )
    return 1 if hourly else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--fix", action="store_true", help="trim images and log retention")
    ap.add_argument("--region", default=None)
    args = ap.parse_args(argv)
    session = boto3.Session(region_name=args.region) if args.region else boto3.Session()
    try:
        who = session.client("sts").get_caller_identity()
    except Exception as exc:  # noqa: BLE001
        print(f"Not signed in to AWS ({type(exc).__name__}). Run `aws login` first.", file=sys.stderr)
        return 2
    print(f"Account {who['Account'][:4]}..., region {session.region_name}\n")
    return report(session.client, apply=args.fix)


if __name__ == "__main__":
    sys.exit(main())
