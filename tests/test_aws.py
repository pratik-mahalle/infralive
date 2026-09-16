import json
from datetime import date
from unittest.mock import Mock

import boto3
import pytest
from botocore.stub import Stubber

from aws_cost_agent.aws import AWS
from aws_cost_agent.config import Config


def client(service):
    return boto3.client(
        service, region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing"
    )


def connector(sdk):
    aws = object.__new__(AWS)
    aws.client = Mock(return_value=sdk)
    aws._prices = {}
    return aws


def test_cost_pagination_and_account_filter():
    ce = client("ce")
    stub = Stubber(ce)
    params = {
        "TimePeriod": {"Start": "2026-08-12", "End": "2026-09-16"},
        "Granularity": "DAILY",
        "Metrics": ["UnblendedCost"],
        "Filter": AWS.cost_filter("123456789012"),
        "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}, {"Type": "DIMENSION", "Key": "REGION"}],
    }

    def page(service, amount):
        return {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": "2026-09-15", "End": "2026-09-16"},
                    "Estimated": True,
                    "Groups": [
                        {
                            "Keys": [service, "us-east-1"],
                            "Metrics": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}},
                        }
                    ],
                }
            ]
        }

    stub.add_response("get_cost_and_usage", {**page("EC2", "10.01"), "NextPageToken": "next"}, params)
    stub.add_response("get_cost_and_usage", page("RDS", "20.99"), {**params, "NextPageToken": "next"})
    adjustment_params = {
        **params,
        "Filter": AWS.cost_filter("123456789012", adjustments=True),
        "GroupBy": [{"Type": "DIMENSION", "Key": "RECORD_TYPE"}],
    }
    credit_page = page("Credit", "-30.00")
    credit_page["ResultsByTime"][0]["Groups"][0]["Keys"] = ["Credit"]
    stub.add_response(
        "get_cost_and_usage", {**credit_page, "NextPageToken": "adjustments-next"}, adjustment_params
    )
    refund_page = page("Refund", "-0.50")
    refund_page["ResultsByTime"][0]["Groups"][0]["Keys"] = ["Refund"]
    stub.add_response(
        "get_cost_and_usage", refund_page, {**adjustment_params, "NextPageToken": "adjustments-next"}
    )
    with stub:
        rows = connector(ce).costs(date(2026, 9, 16), "123456789012")
    assert [r["amount"] for r in rows] == ["10.01", "20.99", "-30.00", "-0.50"]
    assert rows[-2]["record_type"] == "Credit"
    assert rows[-1]["record_type"] == "Refund"
    stub.assert_no_pending_responses()


def test_forecast_end_is_first_of_next_month():
    ce = client("ce")
    stub = Stubber(ce)
    stub.add_response(
        "get_cost_forecast",
        {"Total": {"Amount": "100", "Unit": "USD"}},
        {
            "TimePeriod": {"Start": "2026-12-31", "End": "2027-01-01"},
            "Metric": "UNBLENDED_COST",
            "Granularity": "MONTHLY",
            "PredictionIntervalLevel": 80,
            "Filter": AWS.cost_filter("123456789012"),
        },
    )
    with stub:
        assert connector(ce).forecast(date(2026, 12, 31), "123456789012")["remaining"] == "100"


def test_recommendations_api_shape_and_pagination():
    coh = client("cost-optimization-hub")
    stub = Stubber(coh)
    args = {"filter": {"accountIds": ["123456789012"]}, "includeAllRecommendations": False, "maxResults": 100}
    item = {
        "recommendationId": "rec-1",
        "resourceId": "i-example",
        "region": "us-east-1",
        "estimatedMonthlySavings": 15.12,
        "currencyCode": "USD",
        "actionType": "Rightsize",
        "implementationEffort": "Low",
        "restartNeeded": True,
    }
    stub.add_response("list_recommendations", {"items": [item], "nextToken": "next"}, args)
    stub.add_response("list_recommendations", {"items": []}, {**args, "nextToken": "next"})
    with stub:
        result = connector(coh).recommendations("123456789012")
    assert result[0]["monthly_savings"] == "15.12"
    assert result[0]["restart_needed"] is True


def test_ambiguous_price_is_unknown():
    pricing = Mock()

    def product(price):
        return json.dumps(
            {
                "terms": {
                    "OnDemand": {
                        "x": {
                            "priceDimensions": {
                                "y": {"unit": "Hrs", "beginRange": "0", "pricePerUnit": {"USD": price}}
                            }
                        }
                    }
                }
            }
        )

    pricing.get_products.return_value = {"PriceList": [product("0.12"), product("0.24")]}
    assert connector(pricing).ec2_hourly_rate("us-east-1", "m5.large") is None


def test_spot_instance_never_uses_ondemand_estimate(provider):
    from aws_cost_agent.events import normalize_event

    event = normalize_event(provider.event(), provider.account_id())
    ec2 = Mock()
    ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceType": "m5.large",
                        "PlatformDetails": "Linux/UNIX",
                        "InstanceLifecycle": "spot",
                        "Tags": [{"Key": "Team", "Value": "Payments"}],
                    }
                ]
            }
        ]
    }
    aws = connector(ec2)
    result = aws.enrich_event(event)
    assert result["owner"] == "Payments"
    assert result["estimate"] is None


def test_account_mismatch_rejected():
    sts = Mock()
    sts.get_caller_identity.return_value = {"Account": "999999999999"}
    aws = connector(sts)
    aws.config = Config(account_id="123456789012")
    with pytest.raises(ValueError, match="do not match"):
        aws.account_id()


def test_ses_payload_validated_without_delivery():
    ses = client("sesv2")
    stub = Stubber(ses)
    expected = {
        "FromEmailAddress": "agent@example.com",
        "Destination": {"ToAddresses": ["cto@example.com"]},
        "Content": {
            "Simple": {
                "Subject": {"Data": "Report", "Charset": "UTF-8"},
                "Body": {"Text": {"Data": "Evidence", "Charset": "UTF-8"}},
            }
        },
    }
    stub.add_response("send_email", {"MessageId": "message"}, expected)
    with stub:
        assert (
            connector(ses).send_email(
                {"subject": "Report", "body": "Evidence"},
                Config(sender="agent@example.com", recipients=["cto@example.com"]),
            )
            == "message"
        )


def test_savings_enrollment_is_account_only_and_no_enhanced_metrics():
    sdk = Mock()
    sdk.get_caller_identity.return_value = {"Account": "123456789012"}
    aws = connector(sdk)
    aws.config = Config(account_id="123456789012")
    result = aws.enable_recommendations()
    assert all(r["enabled"] for r in result["results"])
    assert sdk.update_enrollment_status.call_count == 2
    for call in sdk.update_enrollment_status.call_args_list:
        assert call.kwargs == {"status": "Active", "includeMemberAccounts": False}


def test_unused_volume_inventory_paginates_and_excludes_attached():
    from datetime import UTC, datetime

    ec2 = client("ec2")
    stub = Stubber(ec2)
    params = {"Filters": [{"Name": "status", "Values": ["available"]}]}
    volume = {
        "VolumeId": "vol-test",
        "State": "available",
        "Attachments": [],
        "CreateTime": datetime(2026, 1, 1, tzinfo=UTC),
        "Size": 10,
    }
    stub.add_response("describe_volumes", {"Volumes": [volume], "NextToken": "next"}, params)
    stub.add_response(
        "describe_volumes",
        {
            "Volumes": [
                {**volume, "VolumeId": "vol-attached", "Attachments": [{"InstanceId": "i-test"}]},
                {**volume, "VolumeId": "vol-inuse", "State": "in-use"},
                {**volume, "VolumeId": "vol-second"},
            ]
        },
        {**params, "NextToken": "next"},
    )
    with stub:
        result = connector(ec2).unattached_volumes("us-east-1")
    assert [r["resource_id"] for r in result] == ["vol-test", "vol-second"]
    assert result[0]["created_at"] == "2026-01-01T00:00:00+00:00"
    stub.assert_no_pending_responses()


def test_unused_inventory_permission_failure_propagates():
    ec2 = client("ec2")
    stub = Stubber(ec2)
    stub.add_client_error("describe_volumes", service_error_code="UnauthorizedOperation")
    with stub, pytest.raises(Exception, match="UnauthorizedOperation"):
        connector(ec2).unattached_volumes("us-east-1")


def test_cost_allocation_tags_paginate():
    ce = client("ce")
    stub = Stubber(ce)
    stub.add_response(
        "list_cost_allocation_tags",
        {
            "CostAllocationTags": [{"TagKey": "Project", "Status": "Active", "Type": "UserDefined"}],
            "NextToken": "next",
        },
        {"MaxResults": 100},
    )
    stub.add_response(
        "list_cost_allocation_tags",
        {"CostAllocationTags": [{"TagKey": "Owner", "Status": "Inactive", "Type": "UserDefined"}]},
        {"MaxResults": 100, "NextToken": "next"},
    )
    with stub:
        assert connector(ce).allocation_tags() == {"Project": "Active", "Owner": "Inactive"}
    stub.assert_no_pending_responses()


def test_team_costs_use_same_charge_basis_and_preserve_dollars_in_values():
    ce = client("ce")
    stub = Stubber(ce)
    params = {
        "TimePeriod": {"Start": "2026-09-01", "End": "2026-09-16"},
        "Granularity": "MONTHLY",
        "Metrics": ["UnblendedCost"],
        "Filter": AWS.cost_filter("123456789012"),
        "GroupBy": [{"Type": "TAG", "Key": "Project"}],
    }

    def page(key, amount):
        return {
            "ResultsByTime": [
                {
                    "TimePeriod": params["TimePeriod"],
                    "Groups": [
                        {"Keys": [key], "Metrics": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}}}
                    ],
                }
            ]
        }

    stub.add_response("get_cost_and_usage", {**page("Project$A$B", "10"), "NextPageToken": "next"}, params)
    stub.add_response("get_cost_and_usage", page("Project$", "2"), {**params, "NextPageToken": "next"})
    with stub:
        result = connector(ce).team_costs(date(2026, 9, 16), "123456789012", "Project")
    assert [r["value"] for r in result] == ["A$B", ""]
    stub.assert_no_pending_responses()
