"""ECS Fargate services behind one ALB.

    ALB (idle timeout 300 s - WebSockets ping every 20 s)
     ├── /api/*, /ws/*, /m/*, /docs  -> api service (2 tasks, on-demand)
     └── everything else             -> web service (nginx + built SPA)

    worker service   - Fargate Spot, scales on ingest stream backlog
    reclaimer        - Fargate Spot, one task
    replay           - Fargate Spot, one task
    fixtures         - Fargate Spot, one task, only when a football-data.org
                       key is supplied: `cdk deploy -c footballDataSecret=<name>`
                       naming a Secrets Manager secret that holds the key
    social           - Fargate Spot, one task. Mastodon needs nothing; with
                       `-c socialSecret=<name>` (a JSON secret with
                       BLUESKY_HANDLE / BLUESKY_APP_PASSWORD, and optionally the
                       Reddit and X keys) the other sources switch on

Spot for the workers is safe *because* of the design: a reclaimed Spot task's
unacknowledged messages stay pending, its shard leases expire, and the
reclaimer and the remaining workers pick the work up.
"""

from __future__ import annotations

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_applicationautoscaling as appscaling
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from .data_stack import DataStack


class ComputeStack(Stack):
    def __init__(self, scope: Construct, cid: str, *, vpc: ec2.IVpc, data: DataStack,
                 repo_root: str, **kwargs: object) -> None:
        super().__init__(scope, cid, **kwargs)

        cluster = ecs.Cluster(self, "Cluster", vpc=vpc, enable_fargate_capacity_providers=True)
        backend_image = ecs.ContainerImage.from_asset(
            repo_root, file="Dockerfile", target="runtime", platform=ecr_assets.Platform.LINUX_AMD64)
        web_image = ecs.ContainerImage.from_asset(
            f"{repo_root}/frontend", platform=ecr_assets.Platform.LINUX_AMD64)

        env = {
            "ONSIDE_ENV": "aws",
            "ONSIDE_TABLE": data.table.table_name,
            "ONSIDE_REDIS_URL": data.redis_url,
            "ONSIDE_ARCHIVE_URI": f"s3://{data.archive.bucket_name}/events",
            "ONSIDE_S3_ENDPOINT": f"https://s3.{self.region}.amazonaws.com",
            "AWS_DEFAULT_REGION": self.region,
        }
        app_sg = ec2.SecurityGroup(self, "AppSg", vpc=vpc, description="Onside tasks")

        def task(name: str, command: list[str], *, cpu: int = 512, memory: int = 1024,
                 image: ecs.ContainerImage = backend_image, port: int | None = None,
                 secrets: dict[str, ecs.Secret] | None = None) -> ecs.FargateTaskDefinition:
            td = ecs.FargateTaskDefinition(self, f"{name}Task", cpu=cpu, memory_limit_mib=memory)
            c = td.add_container(
                name, image=image, command=command or None, environment=env if image is backend_image else {},
                secrets=secrets,
                logging=ecs.LogDriver.aws_logs(stream_prefix=name, log_retention=logs.RetentionDays.ONE_WEEK),
            )
            if port:
                c.add_port_mappings(ecs.PortMapping(container_port=port))
            if image is backend_image:
                data.table.grant_read_write_data(td.task_role)
                data.archive.grant_read_write(td.task_role)
            return td

        def service(name: str, td: ecs.FargateTaskDefinition, count: int, spot: bool) -> ecs.FargateService:
            return ecs.FargateService(
                self, f"{name}Service", cluster=cluster, task_definition=td, desired_count=count,
                assign_public_ip=True, security_groups=[app_sg],
                capacity_provider_strategies=[ecs.CapacityProviderStrategy(
                    capacity_provider="FARGATE_SPOT" if spot else "FARGATE", weight=1)],
                circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            )

        api = service("Api", task("api", [], port=8080), 2, spot=False)
        web = service("Web", task("web", [], image=web_image, port=80, cpu=256, memory=512), 1, spot=False)
        workers = service("Worker", task("worker", ["python", "-m", "onside.workers.ingest_worker"]), 2, spot=True)
        service("Reclaimer", task("reclaimer", ["python", "-m", "onside.workers.reclaimer"], cpu=256, memory=512),
                1, spot=True)
        service("Replay", task("replay", ["python", "-m", "onside.replay.driver", "--serve"]), 1, spot=True)

        # Today's real fixtures. Opt-in: the key is a secret, never an env value
        # in the template, and without one there is nothing for the task to do.
        fd_secret_name = self.node.try_get_context("footballDataSecret")
        if fd_secret_name:
            fd_secret = secretsmanager.Secret.from_secret_name_v2(self, "FootballDataKey", fd_secret_name)
            service("Fixtures", task("fixtures", ["python", "-m", "onside.workers.fixtures"], cpu=256, memory=512,
                                     secrets={"FOOTBALL_DATA_API_KEY": ecs.Secret.from_secrets_manager(fd_secret)}),
                    1, spot=True)

        social_secret_name = self.node.try_get_context("socialSecret")
        social_secrets: dict[str, ecs.Secret] = {}
        if social_secret_name:
            social_secret = secretsmanager.Secret.from_secret_name_v2(self, "SocialKeys", social_secret_name)
            social_secrets = {k: ecs.Secret.from_secrets_manager(social_secret, field=k)
                              for k in ("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD")}
        service("Social", task("social", ["python", "-m", "onside.workers.social"], cpu=256, memory=512,
                               secrets=social_secrets or None), 1, spot=True)

        alb = elbv2.ApplicationLoadBalancer(self, "Alb", vpc=vpc, internet_facing=True, idle_timeout=Duration.seconds(300))
        listener = alb.add_listener("Http", port=80, open=True)
        listener.add_targets("WebTargets", port=80, targets=[web],
                             health_check=elbv2.HealthCheck(path="/", healthy_http_codes="200"))
        listener.add_targets(
            "ApiTargets", port=8080, targets=[api], priority=10,
            conditions=[elbv2.ListenerCondition.path_patterns(["/api/*", "/ws/*", "/m/*", "/docs", "/openapi.json"])],
            health_check=elbv2.HealthCheck(path="/health", healthy_http_codes="200"),
        )

        # Scale the workers on how far behind the ingest streams are. The metric
        # is published by the reclaimer (pending messages across all shards).
        backlog = cw.Metric(namespace="Onside", metric_name="IngestPending", statistic="Maximum",
                            period=Duration.minutes(1))
        scaling = workers.auto_scale_task_count(min_capacity=1, max_capacity=8)
        scaling.scale_on_metric("Backlog", metric=backlog, adjustment_type=appscaling.AdjustmentType.CHANGE_IN_CAPACITY,
                                scaling_steps=[appscaling.ScalingInterval(upper=100, change=-1),
                                               appscaling.ScalingInterval(lower=1000, change=+2),
                                               appscaling.ScalingInterval(lower=5000, change=+4)])

        CfnOutput(self, "Url", value=f"http://{alb.load_balancer_dns_name}")
