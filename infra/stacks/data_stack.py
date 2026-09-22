"""DynamoDB, the S3 archive and Redis.

* DynamoDB on-demand: traffic is spiky (a replay, a demo) and near zero
  otherwise, which is exactly what on-demand pricing is for.
* S3 with Intelligent-Tiering for the Parquet archive: after the seed it is
  read rarely and never written.
* ElastiCache Redis, a single cache.t4g.micro. Streams and pub/sub need Redis
  semantics; a cluster would be the first thing to add under real load.
"""

from __future__ import annotations

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_elasticache as elasticache
from aws_cdk import aws_s3 as s3
from constructs import Construct


class DataStack(Stack):
    def __init__(self, scope: Construct, cid: str, *, vpc: ec2.IVpc, **kwargs: object) -> None:
        super().__init__(scope, cid, **kwargs)

        self.table = ddb.Table(
            self, "Table",
            table_name="onside",
            partition_key=ddb.Attribute(name="PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="SK", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True),
            removal_policy=RemovalPolicy.DESTROY,  # a portfolio stack is torn down between demos
        )
        for gsi in ("GSI1", "GSI2"):
            self.table.add_global_secondary_index(
                index_name=gsi,
                partition_key=ddb.Attribute(name=f"{gsi}PK", type=ddb.AttributeType.STRING),
                sort_key=ddb.Attribute(name=f"{gsi}SK", type=ddb.AttributeType.STRING),
                projection_type=ddb.ProjectionType.ALL,
            )

        self.archive = s3.Bucket(
            self, "Archive",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            lifecycle_rules=[s3.LifecycleRule(transitions=[s3.Transition(
                storage_class=s3.StorageClass.INTELLIGENT_TIERING, transition_after=Duration.days(0))])],
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Redis admits the VPC's own address range rather than the tasks'
        # security group. Naming that group here would point this stack at the
        # compute stack, while compute already points here for the table and
        # bucket - and CloudFormation refuses a cycle between two stacks.
        self.redis_sg = ec2.SecurityGroup(self, "RedisSg", vpc=vpc, description="Redis: in-VPC only")
        self.redis_sg.add_ingress_rule(ec2.Peer.ipv4(vpc.vpc_cidr_block), ec2.Port.tcp(6379),
                                       "tasks to Redis")
        subnets = elasticache.CfnSubnetGroup(
            self, "RedisSubnets", description="Onside Redis",
            subnet_ids=[s.subnet_id for s in vpc.public_subnets],
        )
        self.redis = elasticache.CfnCacheCluster(
            self, "Redis",
            engine="redis", engine_version="7.1", cache_node_type="cache.t4g.micro", num_cache_nodes=1,
            cache_subnet_group_name=subnets.ref, vpc_security_group_ids=[self.redis_sg.security_group_id],
        )
        self.redis_url = f"redis://{self.redis.attr_redis_endpoint_address}:{self.redis.attr_redis_endpoint_port}/0"

        CfnOutput(self, "TableName", value=self.table.table_name)
        CfnOutput(self, "ArchiveBucket", value=self.archive.bucket_name)
