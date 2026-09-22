"""A $20 billing alarm, deployed before anything that costs money.

Billing metrics only exist in us-east-1, so this stack is pinned there
regardless of where the rest deploys.
"""

from __future__ import annotations

from aws_cdk import Duration, Stack
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

THRESHOLD_USD = 20


class BillingStack(Stack):
    def __init__(self, scope: Construct, cid: str, *, email: str, **kwargs: object) -> None:
        super().__init__(scope, cid, **kwargs)
        topic = sns.Topic(self, "BillingTopic", display_name="Onside billing alarm")
        if email:
            topic.add_subscription(subs.EmailSubscription(email))
        alarm = cw.Alarm(
            self, "Over20",
            alarm_description=f"Estimated AWS charges passed ${THRESHOLD_USD} this month.",
            metric=cw.Metric(namespace="AWS/Billing", metric_name="EstimatedCharges",
                             dimensions_map={"Currency": "USD"}, statistic="Maximum",
                             period=Duration.hours(6)),
            threshold=THRESHOLD_USD, evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
        )
        alarm.add_alarm_action(cw_actions.SnsAction(topic))
