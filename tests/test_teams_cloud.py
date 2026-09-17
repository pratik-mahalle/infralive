import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from aws_cost_agent.cloud_client import cloud_status
from aws_cost_agent.cloud_runtime import runtime_config, tick
from aws_cost_agent.teams import collect_teams, summarize_group


def test_team_totals_keep_unassigned_and_do_not_merge_a_real_tag_value():
    rows = [
        {"value": "Platform", "amount": "5.555", "currency": "USD"},
        {"value": "", "amount": "2.445", "currency": "USD"},
        {"value": "Unassigned", "amount": "2", "currency": "USD"},
    ]
    groups = summarize_group(rows, "10.00", "USD")
    assert len(groups) == 3
    assert next(g for g in groups if g["unassigned"])["amount"] == "2.44"
    assert next(g for g in groups if g["id"] == "Unassigned")["unassigned"] is False


@pytest.mark.parametrize(
    "rows,total",
    [
        ([{"value": "x", "amount": "NaN", "currency": "USD"}], "0.00"),
        ([{"value": "x", "amount": "10", "currency": "EUR"}], "10.00"),
        ([{"value": "x", "amount": "9", "currency": "USD"}], "10.00"),
    ],
)
def test_invalid_or_mismatched_tag_totals_are_not_presented_as_complete(rows, total):
    with pytest.raises(ValueError):
        summarize_group(rows, total, "USD")


def test_missing_tags_show_real_total_without_claiming_resources_untagged(config):
    provider = Mock()
    provider.allocation_tags.return_value = {"Environment": "Active"}
    result = collect_teams(
        provider,
        config,
        date(2026, 9, 16),
        "123456789012",
        {"spend_before_credits": "121.21", "currency": "USD"},
    )
    for dimension in result["dimensions"]:
        assert dimension["state"] == "not_active"
        assert dimension["groups"][0]["amount"] == "121.21"
        assert "Apply it" in dimension["message"]
    provider.team_costs.assert_not_called()


def test_project_and_owner_are_independent_not_added_together(config):
    provider = Mock()
    provider.allocation_tags.return_value = {"Project": "Active", "Owner": "Active"}
    provider.team_costs.return_value = [{"value": "Team", "amount": "10", "currency": "USD"}]
    result = collect_teams(
        provider,
        config,
        date(2026, 9, 16),
        "123456789012",
        {"spend_before_credits": "10.00", "currency": "USD"},
    )
    assert result["total"] == "10.00"
    assert all(r["state"] == "available" for r in result["dimensions"])
    assert provider.team_costs.call_count == 2


def test_tag_permission_error_does_not_leak_aws_response(config):
    provider = Mock()
    provider.allocation_tags.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "secret"}}, "List"
    )
    result = collect_teams(
        provider,
        config,
        date(2026, 9, 16),
        "123456789012",
        {"spend_before_credits": "10.00", "currency": "USD"},
    )
    assert "AccessDenied" in result["dimensions"][0]["message"]
    assert "secret" not in json.dumps(result)


def test_runtime_strips_operator_credentials_and_disables_email(tmp_path):
    c = runtime_config(
        {
            "account_id": "123456789012",
            "profile": "admin",
            "role_arn": "role",
            "external_id": "secret",
            "delivery": "ses",
            "recipients": ["someone@example.com"],
            "sender": "sender@example.com",
            "cloud_bucket": "loop",
            "cloud_function": "loop",
            "monthly_budget": "55.20",
        },
        str(tmp_path),
        "123456789012",
    )
    assert c.profile is None and not c.role_arn and not c.external_id
    assert c.delivery == "preview" and not c.recipients and not c.sender
    assert not c.cloud_bucket and not c.cloud_function
    assert c.monthly_budget == Decimal("55.20")
    with pytest.raises(ValueError, match="account mismatch"):
        runtime_config({"account_id": "other"}, str(tmp_path), "123456789012")


def test_cloud_tick_sync_interval_survives_new_process_and_never_sends_mail(store, config, monkeypatch):
    now = datetime(2026, 9, 16, 12, tzinfo=UTC)
    sync = Mock()
    history = Mock(return_value={"warnings": []})
    poll = Mock()
    provider = Mock()
    monkeypatch.setattr("aws_cost_agent.cloud_runtime.sync", sync)
    monkeypatch.setattr("aws_cost_agent.cloud_runtime.collect_history", history)
    monkeypatch.setattr("aws_cost_agent.cloud_runtime.poll", poll)
    tick(store, provider, config, now=now)
    tick(store, provider, config, now=now + timedelta(minutes=5))
    assert sync.call_count == 1 and history.call_count == 2
    tick(store, provider, config, now=now + timedelta(hours=6))
    assert sync.call_count == 2
    provider.send_email.assert_not_called()
    assert store.metadata("cloud_monitor")["errors"] == []


def test_failed_cost_check_still_collects_history_and_saves_health(store, config, monkeypatch):
    monkeypatch.setattr("aws_cost_agent.cloud_runtime.sync", Mock(side_effect=RuntimeError("secret")))
    history = Mock(return_value={"warnings": []})
    monkeypatch.setattr("aws_cost_agent.cloud_runtime.collect_history", history)
    monkeypatch.setattr("aws_cost_agent.cloud_runtime.poll", Mock())
    result = tick(store, Mock(), config)
    assert result["errors"] == ["Cost collection failed (RuntimeError)"]
    assert history.called
    assert store.metadata("cloud_monitor") == result


def test_cloud_health_exposes_missing_heartbeat_and_never_claims_local_worker_running(store, config):
    config.cloud_region = "us-east-1"
    config.cloud_function = "cloudpulse-monitor"
    result = cloud_status(store, config)
    assert result["monitoring"]["healthy"] is False
    assert result["worker"]["running"] is False
    assert result["notifications"]["delivery"] == "disabled"
    with store.transaction():
        store.save_metadata("cloud_monitor", {"checked_at": datetime.now(UTC).isoformat(), "errors": []})
    assert cloud_status(store, config)["monitoring"]["healthy"] is True
    with store.transaction():
        store.save_metadata(
            "cloud_monitor",
            {"checked_at": (datetime.now(UTC) - timedelta(minutes=16)).isoformat(), "errors": []},
        )
    assert cloud_status(store, config)["monitoring"]["healthy"] is False


def test_group_rounding_reconciles_visible_cents():
    groups = summarize_group(
        [{"value": v, "amount": "0.335", "currency": "USD"} for v in ("a", "b", "c")], "1.00", "USD"
    )
    assert sum(Decimal(r["amount"]) for r in groups) == Decimal("1.00")


def test_cloud_writer_busy_cannot_overwrite_state(monkeypatch):
    from aws_cost_agent.cloud_runtime import handler

    for name, value in {"STATE_BUCKET": "bucket", "ACCOUNT_ID": "123456789012", "LOCK_TABLE": "lock"}.items():
        monkeypatch.setenv(name, value)
    lock = Mock()
    lock.put_item.side_effect = ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
    client = Mock(return_value=lock)
    monkeypatch.setattr("aws_cost_agent.cloud_runtime.boto3.client", client)
    context = Mock()
    context.get_remaining_time_in_millis.return_value = 240000
    result = handler({"action": "inbox_update"}, context)
    assert result["ok"] is False
    client.assert_called_once_with("dynamodb")
    lock.delete_item.assert_not_called()


def test_cloud_inbox_mutation_persists_to_s3_and_releases_lock(tmp_path, monkeypatch):
    from io import BytesIO

    from aws_cost_agent.cloud_runtime import handler
    from aws_cost_agent.inbox import inbox_counts
    from aws_cost_agent.store import Store

    for name, value in {"STATE_BUCKET": "bucket", "ACCOUNT_ID": "123456789012", "LOCK_TABLE": "lock"}.items():
        monkeypatch.setenv(name, value)
    original = tmp_path / "original.db"
    store = Store(str(original))
    store.bind_account("123456789012")
    with store.transaction():
        store.enqueue("event:1", "Title", "Evidence")
    feed = store.notification_feed_id()
    store.close()
    s3 = Mock()
    lock = Mock()
    s3.get_object.side_effect = [
        {"Body": BytesIO(json.dumps({"account_id": "123456789012"}).encode())},
        {"Body": BytesIO(original.read_bytes())},
    ]
    monkeypatch.setattr(
        "aws_cost_agent.cloud_runtime.boto3.client", lambda service: lock if service == "dynamodb" else s3
    )
    context = Mock()
    context.get_remaining_time_in_millis.return_value = 240000
    result = handler(
        {"action": "inbox_update", "feed_id": feed, "sequence": 1, "operation": "review"}, context
    )
    assert result["ok"]
    saved = tmp_path / "saved.db"
    saved.write_bytes(s3.put_object.call_args.kwargs["Body"])
    reopened = Store(str(saved))
    assert inbox_counts(reopened)["reviewed"] == 1
    reopened.close()
    lock.delete_item.assert_called_once()
    assert "ConditionExpression" in lock.delete_item.call_args.kwargs
