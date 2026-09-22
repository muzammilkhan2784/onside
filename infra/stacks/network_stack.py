"""VPC with public subnets only.

No NAT gateway: at roughly $33 a month per AZ it would be the single biggest
line on the bill. Fargate tasks get public IPs and a security group that only
accepts traffic from the load balancer, which is the standard trade for a
low-traffic service. DynamoDB and S3 are reached through free gateway
endpoints, so that traffic never leaves the AWS network either way.
"""

from __future__ import annotations

from aws_cdk import Stack
from aws_cdk import aws_ec2 as ec2
from constructs import Construct


class NetworkStack(Stack):
    def __init__(self, scope: Construct, cid: str, **kwargs: object) -> None:
        super().__init__(scope, cid, **kwargs)
        self.vpc = ec2.Vpc(
            self, "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC,
                                                          cidr_mask=24)],
        )
        self.vpc.add_gateway_endpoint("DynamoEndpoint", service=ec2.GatewayVpcEndpointAwsService.DYNAMODB)
        self.vpc.add_gateway_endpoint("S3Endpoint", service=ec2.GatewayVpcEndpointAwsService.S3)
