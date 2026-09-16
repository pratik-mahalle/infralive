import json
from datetime import date
from pathlib import Path

import pytest

from aws_cost_agent.events import normalize_event
from aws_cost_agent.notifications import deliver
from aws_cost_agent.worker import digest, ingest, poll, sync

TODAY = date(2026, 9, 16)


def test_sync_digest_and_event_are_idempotent(store, provider, config):
    for _ in range(2):
        sync(store, provider, config, TODAY)
        digest(store, TODAY)
        ingest(store, provider, config, provider.event())
    assert len(store.events()) == 1
    assert len(store.messages()) == 4  # one idle resource, anomaly, digest and creation
    assert deliver(store, config, provider) == 4
    assert deliver(store, config, provider) == 0
    assert len(list(Path(config.outbox_dir).glob("*.eml"))) == 4
    assert all(m["status"] == "previewed" for m in store.messages())


def test_previewed_messages_are_not_sent_later(store, provider, config):
    sync(store, provider, config, TODAY)
    deliver(store, config, provider)
    config.delivery = "ses"
    assert deliver(store, config, provider) == 0


def test_failed_delivery_retries(store, provider, config, monkeypatch):
    sync(store, provider, config, TODAY)
    config.demo = False
    config.delivery = "ses"
    calls = []

    def fail(*args):
        raise RuntimeError("Do not persist this sensitive response body")

    monkeypatch.setattr(provider, "send_email", fail, raising=False)
    assert deliver(store, config, provider) == 0
    message = store.messages()[0]
    assert message["status"] == "pending"
    assert message["attempts"] == 1
    assert message["error"] == "RuntimeError"
    monkeypatch.setattr(provider, "send_email", lambda *args: calls.append(args))
    assert deliver(store, config, provider) == 2
    assert len(calls) == 2


def test_transaction_rolls_back_event_if_outbox_fails(store, provider, config, monkeypatch):
    monkeypatch.setattr(store, "enqueue", lambda *args: (_ for _ in ()).throw(RuntimeError("disk full")))
    with pytest.raises(RuntimeError):
        ingest(store, provider, config, provider.event())
    assert store.events() == []


def test_failed_cost_sync_preserves_snapshot(store, provider, config, monkeypatch):
    expected = sync(store, provider, config, TODAY)
    monkeypatch.setattr(provider, "costs", lambda *args: [])
    with pytest.raises(ValueError, match="no cost rows"):
        sync(store, provider, config, TODAY)
    assert store.snapshot() == expected


def test_optional_sources_fail_without_faking_zero_savings(store, provider, config, monkeypatch):
    def unavailable(*args):
        raise RuntimeError("AccessDenied")

    monkeypatch.setattr(provider, "recommendations", unavailable)
    monkeypatch.setattr(provider, "forecast", unavailable)
    snapshot = sync(store, provider, config, TODAY)
    assert snapshot["forecast"] is None
    assert snapshot["recommendations"] == []
    assert len(snapshot["warnings"]) == 2
    assert snapshot["analysis"]["month_to_date"] == "4035.00"


def test_database_cannot_mix_accounts(store):
    store.bind_account("123456789012")
    with pytest.raises(ValueError, match="different AWS account"):
        store.bind_account("999999999999")


def test_failed_api_call_ignored(provider):
    event = provider.event()
    event["detail"]["errorCode"] = "AccessDenied"
    assert normalize_event(event, provider.account_id()) is None


def test_foreign_account_event_rejected(provider):
    event = provider.event()
    event["account"] = "999999999999"
    with pytest.raises(ValueError, match="account"):
        normalize_event(event, provider.account_id())


def test_unknown_api_ignored(provider):
    event = provider.event()
    event["detail"]["eventName"] = "DeleteVolume"
    assert normalize_event(event, provider.account_id()) is None


def test_principal_preserved_without_human_guess(provider):
    event = normalize_event(provider.event(), provider.account_id())
    assert "assumed-role/deploy/pipeline" in event["actor"]
    assert event["owner"] == "Unassigned"
    assert event["estimate"] is None


def test_enrichment_failure_does_not_lose_event(store, provider, config, monkeypatch):
    def unavailable(*args):
        raise RuntimeError("AccessDenied")

    monkeypatch.setattr(provider, "enrich_event", unavailable)
    assert ingest(store, provider, config, provider.event())
    event = store.events()[0]
    assert event["estimate"] is None
    assert "enrichment_warning" in event
    assert len(store.messages()) == 1


def test_sqs_ack_happens_after_commit(store, provider, config, monkeypatch):
    config.queues = {"us-east-1": "queue"}
    message = {"Body": json.dumps(provider.event()), "ReceiptHandle": "receipt"}
    monkeypatch.setattr(provider, "receive", lambda *args: [message], raising=False)
    calls = []

    def acknowledge(*args):
        assert len(store.events()) == 1
        assert len(store.messages()) == 1
        calls.append(args)

    monkeypatch.setattr(provider, "acknowledge", acknowledge, raising=False)
    assert poll(store, provider, config) == 1
    assert poll(store, provider, config) == 0
    assert len(calls) == 2  # duplicate acknowledged without duplicate mail


def test_malformed_sqs_message_is_not_acknowledged(store, provider, config, monkeypatch):
    config.queues = {"us-east-1": "queue"}
    monkeypatch.setattr(
        provider, "receive", lambda *args: [{"Body": "invalid json", "ReceiptHandle": "r"}], raising=False
    )
    calls = []
    monkeypatch.setattr(provider, "acknowledge", lambda *args: calls.append(args), raising=False)
    assert poll(store, provider, config) == 0
    assert calls == []


def test_monthly_budget_alert_deduplicates(store, provider, config):
    config.monthly_budget = 100
    sync(store, provider, config, TODAY)
    sync(store, provider, config, TODAY)
    assert len([m for m in store.messages() if m["id"].startswith("budget:")]) == 1
