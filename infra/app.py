#!/usr/bin/env python3
"""Onside on AWS, two ways.

    cd infra && pip install -r requirements.txt
    npx aws-cdk synth                      # CI does only this

The free tier - CloudFront, Lambda, DynamoDB, EventBridge, all inside AWS's
always-free allowances; no replays or WebSockets (stacks/free_stack.py):

    python onside_secrets.py                      # keys from ../.env into SSM, once
    npx aws-cdk deploy OnsideFree

The full deployment - ECS Fargate, ElastiCache, an ALB - roughly $35 a month
while running; `npx aws-cdk destroy` between demos takes it to zero. Its
billing alarm stack deploys first:

    npx aws-cdk deploy OnsideBilling OnsideNetwork OnsideData OnsideCompute
"""

from __future__ import annotations

import os
from pathlib import Path

import aws_cdk as cdk
from stacks.billing_stack import BillingStack
from stacks.compute_stack import ComputeStack
from stacks.data_stack import DataStack
from stacks.free_stack import FreeStack
from stacks.network_stack import NetworkStack

REPO_ROOT = str(Path(__file__).resolve().parents[1])

app = cdk.App()
env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
                      region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"))
billing = BillingStack(app, "OnsideBilling", env=cdk.Environment(account=env.account, region="us-east-1"),
                       email=app.node.try_get_context("alarmEmail") or "")
network = NetworkStack(app, "OnsideNetwork", env=env)
data = DataStack(app, "OnsideData", vpc=network.vpc, env=env)
compute = ComputeStack(app, "OnsideCompute", vpc=network.vpc, data=data, repo_root=REPO_ROOT, env=env)
for stack in (network, data, compute):
    # `add_stack_dependency` on newer CDK, `add_dependency` before it.
    depend = getattr(stack, "add_stack_dependency", None) or stack.add_dependency
    depend(billing)  # nothing that costs money deploys before the alarm
# No billing dependency: nothing in it charges by the hour.
FreeStack(app, "OnsideFree", repo_root=REPO_ROOT, env=env)
cdk.Tags.of(app).add("project", "onside")

if __name__ == "__main__":
    assembly = app.synth()
    print(f"Synthesised {len(assembly.stacks)} stacks to {assembly.directory}")
    for s in assembly.stacks:
        print(f"  {s.stack_name}: {len(s.template.get('Resources', {}))} resources")
