import json
from pathlib import Path

import pytest

from aws_cost_agent.events import PROVISION_ACTIONS, normalize_event


@pytest.mark.parametrize(
    "source,action,request_params,response,expected",
    [
        ("s3", "CreateBucket", {"bucketName": "new-bucket"}, {}, "new-bucket"),
        ("eks", "CreateCluster", {"name": "new-cluster"}, {}, "new-cluster"),
        (
            "ecs",
            "CreateService",
            {},
            {"service": {"serviceArn": "arn:aws:ecs:us-east-1:123456789012:service/new"}},
            "arn:aws:ecs:us-east-1:123456789012:service/new",
        ),
        ("dynamodb", "CreateTable", {"tableName": "new-table"}, {}, "new-table"),
        (
            "sqs",
            "CreateQueue",
            {},
            {"queueUrl": "https://sqs.us-east-1.amazonaws.com/123456789012/new"},
            "https://sqs.us-east-1.amazonaws.com/123456789012/new",
        ),
        ("newservice", "CreateSomething", {}, {}, "ID unavailable"),
        ("ec2", "AllocateAddress", {}, {"allocationId": "eipalloc-new"}, "eipalloc-new"),
    ],
)
def test_management_creation_across_services(provider, source, action, request_params, response, expected):
    event = provider.event()
    event["detail"].update(
        eventSource=source + ".amazonaws.com",
        eventName=action,
        requestParameters=request_params,
        responseElements=response,
        eventCategory="Management",
    )
    result = normalize_event(event, provider.account_id())
    assert result["service"] == source
    assert result["resource_ids"] == [expected]


@pytest.mark.parametrize(
    "fields",
    [
        {"readOnly": True},
        {"eventCategory": "Data"},
        {"responseElements": {"errorCode": "InvalidRequest"}},
        {"responseElements": {"failures": [{"reason": "Capacity unavailable"}]}},
    ],
)
def test_read_data_and_failed_requests_are_not_creation_alerts(provider, fields):
    event = provider.event()
    event["detail"].update(fields)
    assert normalize_event(event, provider.account_id()) is None


def test_eventbridge_pattern_matches_backend_creation_coverage():
    root = Path(__file__).resolve().parents[1]
    template = json.loads((root / "infra/events.json").read_text())
    pattern = template["Resources"]["CreationRule"]["Properties"]["EventPattern"]
    assert "source" not in pattern
    actions = pattern["detail"]["eventName"]
    assert {"prefix": "Create"} in actions
    assert PROVISION_ACTIONS == {a for a in actions if isinstance(a, str)}
