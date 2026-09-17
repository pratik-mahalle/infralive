import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from botocore.exceptions import ClientError

from aws_cost_agent.events import normalize_event
from aws_cost_agent.history import collect_history
from aws_cost_agent.savings import recommendation_status, review_leads

NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


def event(provider, event_id, when, action="CreateBucket"):
    detail = provider.event()["detail"]
    detail.update(
        eventID=event_id,
        eventTime=when.isoformat(),
        eventName=action,
        eventSource="s3.amazonaws.com",
        requestParameters={"bucketName": event_id},
        responseElements={},
    )
    return {"CloudTrailEvent": json.dumps(detail)}


def test_history_backfills_then_notifies_only_new_creations(store, config, provider):
    config.demo = False
    provider.history_page = Mock(return_value={"Events": [event(provider, "old", NOW - timedelta(days=1))]})
    result = collect_history(store, provider, config, NOW)
    assert result["regions"][0]["added"] == 1
    assert len(store.events()) == 1
    assert store.messages() == []
    provider.history_page.return_value = {
        "Events": [
            event(provider, "new", NOW + timedelta(minutes=1)),
            event(provider, "old", NOW - timedelta(days=1)),
            event(provider, "update", NOW + timedelta(minutes=2), "UpdateBucket"),
        ]
    }
    collect_history(store, provider, config, NOW + timedelta(minutes=5))
    collect_history(store, provider, config, NOW + timedelta(minutes=10))
    assert len(store.events()) == 3
    assert len(store.messages()) == 1
    assert store.messages()[0]["id"].endswith(":new")


def test_history_pagination_resumes_fixed_window(store, config, provider):
    config.demo = False
    provider.history_page = Mock(return_value={"Events": [], "NextToken": "next-page"})
    result = collect_history(store, provider, config, NOW)
    assert result["regions"][0]["backfill_pending"]
    first_end = provider.history_page.call_args.args[2]
    assert provider.history_page.call_count == 10
    provider.history_page.reset_mock()
    provider.history_page.return_value = {"Events": []}
    collect_history(store, provider, config, NOW + timedelta(minutes=5))
    assert provider.history_page.call_args.args[2] == first_end
    assert provider.history_page.call_args.args[3] == "next-page"
    assert store.metadata("history:us-east-1")["backfilled"]


def test_history_permission_failure_is_visible_without_losing_events(store, config, provider):
    config.demo = False
    provider.history_page = Mock(
        side_effect=ClientError({"Error": {"Code": "AccessDeniedException"}}, "LookupEvents")
    )
    result = collect_history(store, provider, config, NOW)
    assert "LookupEvents" in result["warnings"][0]
    assert store.metadata("history:us-east-1") is None


def test_updates_are_displayed_but_not_treated_as_creation(provider):
    envelope = provider.event()
    envelope["detail"]["eventName"] = "UpdateService"
    assert normalize_event(envelope, provider.account_id()) is None
    result = normalize_event(envelope, provider.account_id(), include_changes=True)
    assert result["change_kind"] == "change"
    assert "Creation" not in result["status"]


def test_spending_leads_are_not_savings_estimates():
    result = review_leads(
        {
            "currency": "USD",
            "top_services": [
                {"service": "Amazon Elastic Container Service", "amount": "63.17"},
                {"service": "AmazonCloudWatch", "amount": "0.00"},
            ],
        }
    )
    assert len(result) == 1
    assert result[0]["period_spend"] == "63.17"
    assert result[0]["savings_estimate"] is None


def test_not_enrolled_is_distinct_from_denied_permissions():
    error = ClientError(
        {
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "AWS account is not enrolled for recommendations.",
            }
        },
        "ListRecommendations",
    )
    assert recommendation_status(error)["state"] == "not_enrolled"
    error = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "Not authorized"}}, "ListRecommendations"
    )
    assert recommendation_status(error)["state"] == "access_denied"


def test_history_checks_do_not_race_another_collector(store, config, provider):
    from aws_cost_agent.locking import worker_lock

    config.demo = False
    provider.history_page = Mock()
    with worker_lock(config.database + ".history"):
        result = collect_history(store, provider, config, NOW)
    assert "in progress" in result["warnings"][0]
    provider.history_page.assert_not_called()


def test_routine_activity_is_stored_but_not_paged_by_default(store, config, provider):
    config.demo = False
    provider.history_page = Mock(return_value={"Events": []})
    collect_history(store, provider, config, NOW)
    provider.history_page.return_value = {
        "Events": [event(provider, "log-stream", NOW + timedelta(minutes=1), "CreateLogStream")]
    }
    collect_history(store, provider, config, NOW + timedelta(minutes=5))
    assert len(store.events()) == 1
    assert store.events(include_routine=False) == []
    assert store.messages() == []
