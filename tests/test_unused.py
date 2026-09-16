from datetime import UTC, datetime, timedelta

import pytest

from aws_cost_agent.config import load_config
from aws_cost_agent.unused import collect_unused, track_unused

NOW = datetime(2026, 9, 1, tzinfo=UTC)
ACCOUNT = "123456789012"
VOLUME = {
    "resource_id": "vol-test",
    "region": "us-east-1",
    "source": "EC2 DescribeVolumes",
    "resource_type": "EBS volume",
    "created_at": "2025-01-01T00:00:00+00:00",
    "signal": "Unattached at every successful check",
}


def observe(store, config, now, volumes=None, recommendations=None):
    with store.transaction():
        return track_unused(
            store, [VOLUME] if volumes is None else volumes, recommendations or [], config, ACCOUNT, now
        )


def creation(store, **kwargs):
    event = {
        "id": "creation-1",
        "time": "2025-01-01T00:00:00+00:00",
        "account_id": ACCOUNT,
        "region": "us-east-1",
        "service": "ec2",
        "action": "CreateVolume",
        "resource_ids": ["vol-test"],
        "actor": "arn:aws:sts::123456789012:assumed-role/Deploy/ci",
        **kwargs,
    }
    with store.transaction():
        store.add_event(event)
    return event


def test_age_alone_does_not_establish_idle_time(store, config):
    result = observe(store, config, NOW)
    assert result[0]["observed_days"] == 0
    assert not result[0]["ready"]
    assert store.messages() == []


def test_seven_days_creator_and_reminders_persist(store, config):
    creation(store)
    for hours in range(0, 169, 6):
        result = observe(store, config, NOW + timedelta(hours=hours))
    assert result[0]["ready"]
    assert result[0]["observed_days"] == 7
    assert len(store.messages()) == 1
    body = store.messages()[0]["body"]
    assert "assumed-role/Deploy/ci" in body
    assert "not proof of continuous inactivity" in body
    assert "not yet measured" in body
    assert store.alerts_after(0)["alerts"][0]["kind"] == "idle"
    for hours in range(174, 337, 6):
        observe(store, config, NOW + timedelta(hours=hours))
    assert len(store.messages()) == 2


@pytest.mark.parametrize("reason", ["used", "missing", "offline", "attachment", "recreated"])
def test_usage_or_missing_evidence_resets_duration(store, config, reason):
    for hours in range(0, 145, 6):
        observe(store, config, NOW + timedelta(hours=hours))
    if reason in {"used", "missing"}:
        observe(store, config, NOW + timedelta(hours=150), volumes=[])
    if reason == "attachment":
        creation(store, action="AttachVolume", time=(NOW + timedelta(hours=149)).isoformat())
    if reason == "recreated":
        creation(store, time=(NOW + timedelta(hours=149)).isoformat())
    result = observe(store, config, NOW + timedelta(hours=168 if reason == "offline" else 156))
    assert result[0]["observed_days"] == 0
    assert store.messages() == []


def test_no_invented_creator_and_notifications_can_be_disabled(store, config):
    config.idle_alerts = False
    config.unused_after_days = 1
    for hours in range(0, 25, 6):
        result = observe(store, config, NOW + timedelta(hours=hours))
    assert result[0]["ready"] and result[0]["creator"] is None
    assert store.messages() == []


def test_creator_match_is_scoped_and_never_uses_related_arn(store):
    store.bind_account(ACCOUNT)
    creation(store)
    assert store.creation_for(f"arn:aws:ec2:us-east-1:{ACCOUNT}:volume/vol-test", "us-east-1")
    assert store.creation_for("vol-test", "eu-west-1") is None
    assert store.creation_for("arn:aws:ec2:us-east-1:999999999999:volume/vol-test", "us-east-1") is None
    creation(store, id="stack", action="CreateStack", resource_ids=["i-related"])
    assert store.creation_for("i-related", "us-east-1") is None


def test_failure_does_not_return_partial_inventory(config):
    config.demo = False

    class Failing:
        def unattached_volumes(self, region):
            raise PermissionError("secret detail")

    volumes, warnings = collect_unused(Failing(), config)
    assert volumes == []
    assert "PermissionError" in warnings[0] and "secret detail" not in warnings[0]


def test_aws_idle_evidence_under_cost_threshold_can_trigger_duration_alert(store, config):
    config.unused_after_days = 1
    for hours in range(0, 25, 6):
        now = NOW + timedelta(hours=hours)
        recommendation = {
            "id": "rotating-" + str(hours),
            "resource_id": "i-test",
            "region": "us-east-1",
            "action_type": "Stop",
            "monthly_savings": "2.00",
            "currency": "USD",
            "last_refresh": now.isoformat(),
            "source": "AWS Cost Optimization Hub",
        }
        result = observe(store, config, now, volumes=[], recommendations=[recommendation])
    assert result[0]["ready"] and len(store.messages()) == 1
    assert "USD 2.00/month" in store.messages()[0]["body"]
    result = observe(store, config, now + timedelta(hours=6), volumes=[], recommendations=[])
    assert result == []


def test_tracking_and_alerts_roll_back_together(store, config):
    observe(store, config, NOW)
    old = store.metadata("unused_observations")
    with pytest.raises(RuntimeError):
        with store.transaction():
            track_unused(store, [], [], config, ACCOUNT, NOW + timedelta(hours=6))
            raise RuntimeError("rollback")
    assert store.metadata("unused_observations") == old


@pytest.mark.parametrize("days", [0, 366])
def test_duration_config_validated(tmp_path, days):
    path = tmp_path / "config.toml"
    path.write_text(f"[agent]\nunused_after_days = {days}\n")
    with pytest.raises(ValueError, match="unused_after_days"):
        load_config(str(path))


def test_duration_notice_suppresses_same_sync_cost_reminder(store, config):
    from aws_cost_agent.idle import idle_candidates, queue_idle_alerts

    config.unused_after_days = 1
    for hours in range(0, 25, 6):
        now = NOW + timedelta(hours=hours)
        recommendations = [
            {
                "id": "aws-id",
                "resource_id": "i-test",
                "region": "us-east-1",
                "action_type": "Stop",
                "monthly_savings": "40.00",
                "currency": "USD",
                "last_refresh": now.isoformat(),
                "source": "AWS Cost Optimization Hub",
            }
        ]
        observe(store, config, now, volumes=[], recommendations=recommendations)
    with store.transaction():
        queue_idle_alerts(store, idle_candidates(recommendations, config, now), config, ACCOUNT, now)
    assert len(store.messages()) == 1
