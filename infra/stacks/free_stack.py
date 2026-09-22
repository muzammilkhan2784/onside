"""Onside on AWS's always-free services: CloudFront, Lambda, DynamoDB, EventBridge.

    CloudFront ─┬─ /api/*, /m/*, /docs, /openapi.json, /health ─▶ Lambda "api"
                │     (function URL, signed by CloudFront; cached as the API's
                │      Cache-Control says - a minute for most of it)
                └─ everything else ─▶ S3: the built web app

    EventBridge ── every minute ─▶ Lambda "worker" {"job": "fixtures"}
                └─ every 5 min  ─▶ Lambda "worker" {"job": "social"}

    DynamoDB  "onside-free"     the archive's documents (on-demand; a few
                                cents to seed, then reads at $0.125 a million)
              "onside-free-kv"  what Redis holds in the full deployment -
                                fixtures, tables, posts (provisioned 20/20,
                                inside the always-free 25/25)

What this leaves out, on purpose: ElastiCache, Fargate, NAT and a load
balancer - the four things that cost money every hour. So there is no Redis,
and so no replays and no WebSockets; the web app asks /api/features and hides
them. Everything else - the archive, current football, the social feed - is
the same code as the full deployment.

Secrets (the football-data.org key, the Bluesky app password) are SecureString
parameters under /onside/, written by `python infra/onside_secrets.py`; CloudFormation
never sees them.
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudfront as cf
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

SSM_PATH = "/onside"
#: The SPA's routes have no file extension; send them to index.html. The API
#: paths have their own behaviours, so this never sees them.
SPA_REWRITE = """
function handler(event) {
  var req = event.request;
  var last = req.uri.split('/').pop();
  if (last.indexOf('.') === -1) { req.uri = '/index.html'; }
  return req;
}
"""


class FreeStack(Stack):
    def __init__(self, scope: Construct, cid: str, *, repo_root: str, **kwargs: object) -> None:
        super().__init__(scope, cid, **kwargs)

        # ------------------------------------------------------------ data
        table = ddb.Table(
            self, "Table",
            table_name="onside-free",
            partition_key=ddb.Attribute(name="PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="SK", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )
        for gsi in ("GSI1", "GSI2"):
            table.add_global_secondary_index(
                index_name=gsi,
                partition_key=ddb.Attribute(name=f"{gsi}PK", type=ddb.AttributeType.STRING),
                sort_key=ddb.Attribute(name=f"{gsi}SK", type=ddb.AttributeType.STRING),
                projection_type=ddb.ProjectionType.ALL,
            )
        kv = ddb.Table(
            self, "Kv",
            table_name="onside-free-kv",
            partition_key=ddb.Attribute(name="PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="SK", type=ddb.AttributeType.STRING),
            # Provisioned, not on-demand: 20 + 20 sits inside DynamoDB's
            # always-free 25 read and 25 write units, and bursts draw on the
            # five minutes of unused capacity DynamoDB banks.
            billing_mode=ddb.BillingMode.PROVISIONED,
            read_capacity=20,
            write_capacity=20,
            time_to_live_attribute="exp",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ------------------------------------------------------------ compute
        def image(cmd: list[str] | None = None) -> lambda_.DockerImageCode:
            return lambda_.DockerImageCode.from_image_asset(
                repo_root, file="Dockerfile", target="lambda", cmd=cmd,
                platform=ecr_assets.Platform.LINUX_AMD64,
                # Neither image needs these, and leaving them out keeps a web
                # app change from rebuilding the Lambda image.
                exclude=["frontend", "infra", "demo", "benchmarks", ".github", "*.md"],
            )

        env = {
            "ONSIDE_TABLE": table.table_name,
            "ONSIDE_KV_TABLE": kv.table_name,
            # Lambda allows ten seconds to start. The first start after a
            # deploy pulls the image and can take longer; with async init the
            # adapter hands over in time and the first request waits for the
            # app, instead of Lambda starting the whole thing again.
            "AWS_LWA_ASYNC_INIT": "true",
        }

        def logs_for(name: str) -> logs.LogGroup:
            return logs.LogGroup(
                self, f"{name}Logs", log_group_name=f"/aws/lambda/onside-free-{name}",
                retention=logs.RetentionDays.THREE_DAYS, removal_policy=RemovalPolicy.DESTROY,
            )

        api = lambda_.DockerImageFunction(
            self, "Api",
            function_name="onside-free-api",
            code=image(),
            memory_size=1769,  # one full vCPU, for DuckDB's scans of the archive
            timeout=Duration.seconds(30),
            architecture=lambda_.Architecture.X86_64,
            environment=env,
            log_group=logs_for("api"),
        )
        table.grant_read_data(api)
        kv.grant_read_data(api)

        worker = lambda_.DockerImageFunction(
            self, "Worker",
            function_name="onside-free-worker",
            code=image(["python", "-m", "onside.serverless", "worker"]),
            memory_size=512,
            timeout=Duration.minutes(3),
            architecture=lambda_.Architecture.X86_64,
            environment={
                **env,
                "ONSIDE_SSM_PATH": SSM_PATH,
                "ONSIDE_SOCIAL_EVERY_S": "300",
                "AWS_LWA_READINESS_CHECK_PATH": "/health",
                # A job that fails is a failed invocation, visible in metrics.
                "AWS_LWA_ERROR_STATUS_CODES": "500-599",
            },
            # A missed minute is simply the next minute's job; never retry.
            retry_attempts=0,
            max_event_age=Duration.minutes(2),
            log_group=logs_for("worker"),
        )
        kv.grant_read_write_data(worker)
        worker.add_to_role_policy(iam.PolicyStatement(
            actions=["ssm:GetParametersByPath"],
            resources=[self.format_arn(service="ssm", resource="parameter", resource_name=SSM_PATH.strip("/"))],
        ))

        for job, every in (("fixtures", Duration.minutes(1)), ("social", Duration.minutes(5))):
            events.Rule(
                self, f"{job.title()}Schedule",
                schedule=events.Schedule.rate(every),
                targets=[targets.LambdaFunction(
                    worker, event=events.RuleTargetInput.from_object({"job": job}), retry_attempts=0,
                )],
            )

        # ------------------------------------------------------------ edge
        site = s3.Bucket(
            self, "Site",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        # Only CloudFront may call the function URL: it signs each request.
        api_origin = origins.FunctionUrlOrigin.with_origin_access_control(
            api.add_function_url(auth_type=lambda_.FunctionUrlAuthType.AWS_IAM)
        )
        api_cache = cf.CachePolicy(
            self, "ApiCache",
            comment="Onside API: cache for as long as the API's Cache-Control says",
            default_ttl=Duration.seconds(0),
            min_ttl=Duration.seconds(0),
            max_ttl=Duration.hours(1),
            query_string_behavior=cf.CacheQueryStringBehavior.all(),
            enable_accept_encoding_gzip=True,
            enable_accept_encoding_brotli=True,
        )
        api_behaviour = cf.BehaviorOptions(
            origin=api_origin,
            viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            allowed_methods=cf.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
            cache_policy=api_cache,
            origin_request_policy=cf.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            compress=True,
        )
        spa = cf.Function(
            self, "SpaRewrite",
            code=cf.FunctionCode.from_inline(SPA_REWRITE),
            runtime=cf.FunctionRuntime.JS_2_0,
        )
        dist = cf.Distribution(
            self, "Cdn",
            comment="Onside (free tier)",
            default_root_object="index.html",
            price_class=cf.PriceClass.PRICE_CLASS_100,
            default_behavior=cf.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site),
                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cf.CachePolicy.CACHING_OPTIMIZED,
                compress=True,
                function_associations=[cf.FunctionAssociation(
                    function=spa, event_type=cf.FunctionEventType.VIEWER_REQUEST)],
            ),
            additional_behaviors={
                path: api_behaviour
                for path in ("/api/*", "/m/*", "/docs", "/openapi.json", "/health")
            },
        )

        # Function URLs now check lambda:InvokeFunction as well as
        # lambda:InvokeFunctionUrl; grant both, to this distribution only.
        api.add_permission(
            "CloudFrontInvoke",
            principal=iam.ServicePrincipal("cloudfront.amazonaws.com"),
            action="lambda:InvokeFunction",
            source_arn=f"arn:aws:cloudfront::{self.account}:distribution/{dist.distribution_id}",
        )

        dist_dir = Path(repo_root) / "frontend" / "dist"
        if (dist_dir / "index.html").exists():
            s3deploy.BucketDeployment(
                self, "SiteFiles",
                sources=[s3deploy.Source.asset(str(dist_dir))],
                destination_bucket=site,
                distribution=dist,
                distribution_paths=["/*"],
                memory_limit=512,
            )

        CfnOutput(self, "SiteUrl", value=f"https://{dist.distribution_domain_name}")
        CfnOutput(self, "TableName", value=table.table_name)
        CfnOutput(self, "KvTableName", value=kv.table_name)
        CfnOutput(self, "WorkerFunction", value=worker.function_name)
