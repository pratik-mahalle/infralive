from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aws_cost_agent.idle import idle_candidates, queue_idle_alerts

NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


def recommendation(**kwargs):
    return {
        "id": "rec-1",
        "resource_id": "vol-unattached",
        "region": "us-east-1",
        "action_type": "Delete",
        "monthly_savings": "40.00",
        "currency": "USD",
        "last_refresh": NOW.isoformat(),
        **kwargs,
    }


def test_aws_idle_finding_crosses_monthly_threshold(config):
    result = idle_candidates([recommendation()], config, NOW)
    assert result[0]["monthly_savings"] == "40.00"
    assert result[0]["action"] == "Delete"


@pytest.mark.parametrize(
    "change",
    [
        {"action_type": "Rightsize"},
        {"action_type": "PurchaseSavingsPlans"},
        {"monthly_savings": "24.99"},
        {"monthly_savings": "0"},
        {"monthly_savings": "NaN"},
        {"monthly_savings": None},
        {"currency": "EUR"},
        {"last_refresh": "Unknown"},
        {"last_refresh": None},
        {"last_refresh": "2026-09-10T00:00:00+00:00"},
        {"last_refresh": "2026-09-17T00:00:00+00:00"},
        {"last_refresh": "2026-09-16T00:00:00"},
        {"resource_id": "Unknown"},
    ],
)
def test_no_idle_claim_without_sufficient_fresh_evidence(config, change):
    assert idle_candidates([recommendation(**change)], config, NOW) == []


def test_idle_reminders_deduplicate_when_aws_recommendation_id_changes(store, config):
    first = idle_candidates([recommendation()], config, NOW)
    with store.transaction():
        queue_idle_alerts(store, first, config, "123456789012", NOW)
    second = idle_candidates([recommendation(id="rotated-id")], config, NOW)
    with store.transaction():
        queue_idle_alerts(store, second, config, "123456789012", NOW + timedelta(days=1))
    assert len(store.messages()) == 1
    with store.transaction():
        queue_idle_alerts(store, second, config, "123456789012", NOW + timedelta(days=7))
    assert len(store.messages()) == 2
    assert len(store.alerts_after(0)["alerts"]) == 2


def test_idle_threshold_and_disable_are_configurable(store, config):
    config.idle_monthly_savings = Decimal("100")
    assert idle_candidates([recommendation()], config, NOW) == []
    config.idle_monthly_savings = Decimal("25")
    config.idle_alerts = False
    with store.transaction():
        queue_idle_alerts(
            store, idle_candidates([recommendation()], config, NOW), config, "123456789012", NOW
        )
    assert store.messages() == []


def test_idle_alert_transaction_rolls_back_reminder_cursor(store, config):
    finding = idle_candidates([recommendation()], config, NOW)
    with pytest.raises(RuntimeError):
        with store.transaction():
            queue_idle_alerts(store, finding, config, "123456789012", NOW)
            raise RuntimeError("transaction failed")
    assert store.messages() == []
    assert store.last_idle_notification(finding[0]["id"]) is None
