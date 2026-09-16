import json
from datetime import date

import pytest

from aws_cost_agent.cli import main
from aws_cost_agent.locking import worker_lock, worker_status
from aws_cost_agent.status import status_payload
from aws_cost_agent.worker import ingest, sync


def test_status_empty_account_is_valid_without_aws(store, config):
    payload = status_payload(store, config)
    assert payload["schema_version"] == 1
    assert payload["snapshot"] is None
    assert payload["events"] == []
    assert payload["worker"]["running"] is False


def test_status_aggregates_exact_daily_amounts(store, config, provider):
    sync(store, provider, config, date(2026, 9, 16))
    ingest(store, provider, config, provider.event())
    payload = status_payload(store, config)
    assert len(payload["daily_totals"]) == 14
    assert payload["daily_totals"][-1]["amount"] == "345.00"
    assert "daily_costs" not in payload["snapshot"]
    assert payload["events"][0]["owner"] == "Payments (demo)"
    assert payload["notifications"]["pending"] == 3


def test_worker_lock_prevents_duplicate_workers_and_releases(config):
    assert worker_status(config.database)["running"] is False
    with worker_lock(config.database):
        assert worker_status(config.database)["running"] is True
        with pytest.raises(ValueError, match="already running"):
            with worker_lock(config.database):
                pass
    # A stale PID in an unlocked file must not be mistaken for a running worker.
    assert worker_status(config.database)["running"] is False


def test_cli_status_does_not_construct_aws(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aws_cost_agent.cli.AWS", lambda *args: pytest.fail("AWS must not be constructed"))
    assert main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["snapshot"] is None


def test_notification_feed_is_paginated_durable_and_independent_of_email(store):
    with store.transaction():
        for i in range(205):
            store.enqueue(f"event:{i}", "A resource was created", "Evidence")
        store.enqueue("digest:today", "Digest", "Not a desktop alert")
        store.enqueue("event:0", "Duplicate", "Duplicate")
    store.delivered("event:0", "sent")
    after, alerts = 0, []
    for _ in range(3):
        page = store.alerts_after(after)
        alerts += page["alerts"]
        after = page["next_cursor"]
    assert len(alerts) == 205
    assert len({a["sequence"] for a in alerts}) == 205
    assert store.alerts_after(after)["alerts"] == []
    assert store.notification_cursor() == after


def test_notification_feed_identity_survives_reopening(store, config):
    from aws_cost_agent.store import Store

    old = store.notification_feed_id()
    reopened = Store(config.database)
    assert reopened.notification_feed_id() == old
    reopened.close()


def test_chart_and_forecast_keep_charge_basis_when_credits_cover_spend(store, config, provider, monkeypatch):
    from decimal import Decimal

    rows = provider.costs(date(2026, 9, 16), "123456789012")
    credits = [{**r, "record_type": "Credit", "amount": str(-Decimal(r["amount"]))} for r in rows]
    monkeypatch.setattr(provider, "costs", lambda *args: rows + credits)
    sync(store, provider, config, date(2026, 9, 16))
    payload = status_payload(store, config)
    assert payload["snapshot"]["analysis"]["month_to_date"] == "0.00"
    assert payload["snapshot"]["forecast"]["month_total"] == "9210.00"
    assert payload["daily_totals"][-1]["amount"] == "345.00"
