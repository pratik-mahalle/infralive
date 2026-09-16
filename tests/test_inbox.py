import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from aws_cost_agent.cli import main
from aws_cost_agent.inbox import inbox_counts, inbox_page, update_inbox
from aws_cost_agent.store import Store

NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


def seed(store, count=3):
    with store.transaction():
        for i in range(count):
            store.enqueue(
                f"event:{i}",
                f"Created resource {i}",
                f"Resource: vol-{i}\nCreator AWS identity: role/engineering",
            )
    return inbox_page(store, now=NOW)["alerts"]


def update(store, alert, action, now=NOW, **kwargs):
    return update_inbox(store, alert["sequence"], alert["feed_id"], action, now=now, **kwargs)


def test_existing_alerts_are_unread_even_after_delivery(store):
    alerts = seed(store)
    store.delivered("event:0", "sent")
    assert inbox_counts(store, NOW) == {"total": 3, "open": 3, "snoozed": 0, "reviewed": 0, "unread": 3}
    assert all(a["unread"] for a in alerts)
    update(store, alerts[0], "read")
    assert inbox_counts(store, NOW)["unread"] == 2
    assert inbox_counts(store, NOW)["open"] == 3
    update(store, alerts[0], "unread")
    assert inbox_counts(store, NOW)["unread"] == 3


def test_review_and_reopen_are_durable_and_do_not_consume_delivery(store, config):
    alert = seed(store, 1)[0]
    original_feed = store.alerts_after(0)
    original_outbox = store.messages()
    update(store, alert, "review")
    reopened = Store(config.database)
    try:
        assert inbox_page(reopened, now=NOW)["alerts"] == []
        reviewed = inbox_page(reopened, "reviewed", now=NOW)["alerts"][0]
        assert reviewed["reviewed_at"] == NOW.isoformat()
        assert not reviewed["unread"]
        update(reopened, reviewed, "reopen")
        assert inbox_counts(reopened, NOW)["unread"] == 1
        assert reopened.alerts_after(0) == original_feed
        assert reopened.messages() == original_outbox
    finally:
        reopened.close()


def test_snooze_expires_exactly_at_deadline_without_worker_or_new_notification(store):
    alert = seed(store, 1)[0]
    original_cursor = store.notification_cursor()
    update(store, alert, "snooze", hours=1)
    assert inbox_counts(store, NOW)["open"] == 0
    assert inbox_counts(store, NOW)["unread"] == 0
    assert (
        inbox_page(store, "snoozed", now=NOW)["alerts"][0]["snoozed_until"]
        == (NOW + timedelta(hours=1)).isoformat()
    )
    update(store, alert, "read", now=NOW + timedelta(minutes=30))
    assert inbox_counts(store, NOW + timedelta(minutes=59))["snoozed"] == 1
    returned = inbox_page(store, now=NOW + timedelta(hours=1))["alerts"][0]
    assert returned["state"] == "open" and returned["unread"]
    assert store.notification_cursor() == original_cursor
    update(store, returned, "read", now=NOW + timedelta(hours=1))
    assert not inbox_page(store, now=NOW + timedelta(hours=1))["alerts"][0]["unread"]


def test_review_snoozed_alert_cancels_its_return(store):
    alert = seed(store, 1)[0]
    update(store, alert, "snooze", hours=24)
    update(store, alert, "review")
    assert inbox_counts(store, NOW + timedelta(days=2))["reviewed"] == 1
    assert inbox_counts(store, NOW + timedelta(days=2))["unread"] == 0
    update(store, alert, "reopen")
    assert inbox_page(store, now=NOW)["alerts"][0]["snoozed_until"] is None


def test_duplicate_enqueue_does_not_reopen_a_reviewed_alert(store):
    alert = seed(store, 1)[0]
    update(store, alert, "review")
    with store.transaction():
        store.enqueue("event:0", "Repeated call", "Duplicate")
        store.enqueue("idle:new-reminder", "New reminder", "New evidence")
    assert inbox_counts(store, NOW)["reviewed"] == 1
    assert inbox_counts(store, NOW)["unread"] == 1


def test_keyset_pagination_survives_new_arrivals_and_includes_all_old_alerts(store):
    seed(store, 123)
    first = inbox_page(store, limit=50, now=NOW)
    with store.transaction():
        store.enqueue("event:new", "New arrival", "Evidence")
    second = inbox_page(store, before=first["next_before"], limit=50, now=NOW)
    third = inbox_page(store, before=second["next_before"], limit=50, now=NOW)
    sequences = [a["sequence"] for p in (first, second, third) for a in p["alerts"]]
    assert len(sequences) == len(set(sequences)) == 123
    assert sequences == sorted(sequences, reverse=True)
    assert third["next_before"] is None
    assert inbox_page(store, now=NOW)["alerts"][0]["title"] == "New arrival"


def test_inbox_identity_prevents_cross_account_sequence_collisions(store, tmp_path):
    alert = seed(store, 1)[0]
    other = Store(str(tmp_path / "other.sqlite3"))
    try:
        seed(other, 1)
        with pytest.raises(ValueError, match="another inbox"):
            update(other, alert, "review")
        assert inbox_counts(other, NOW)["unread"] == 1
        assert inbox_counts(store, NOW)["unread"] == 1
    finally:
        other.close()


@pytest.mark.parametrize("kwargs", [{"state": "invalid"}, {"limit": 0}, {"limit": 101}, {"before": -1}])
def test_invalid_pagination_is_rejected(store, kwargs):
    with pytest.raises(ValueError):
        inbox_page(store, **kwargs)


@pytest.mark.parametrize("action,hours", [("unknown", 24), ("snooze", 0), ("snooze", 721)])
def test_invalid_actions_do_not_change_state(store, action, hours):
    alert = seed(store, 1)[0]
    with pytest.raises(ValueError):
        update(store, alert, action, hours=hours)
    assert inbox_counts(store, NOW)["unread"] == 1
    assert store.db.execute("SELECT COUNT(*) FROM alert_inbox_state").fetchone()[0] == 0


def test_unknown_alert_and_naive_clock_fail_clearly(store):
    with pytest.raises(ValueError, match="not found"):
        update_inbox(store, 100, store.notification_feed_id(), "review")
    with pytest.raises(ValueError, match="timezone"):
        inbox_counts(store, datetime(2026, 9, 16))


def test_old_database_migrates_without_losing_alerts(tmp_path):
    path = str(tmp_path / "old.sqlite3")
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE notification_feed (sequence INTEGER PRIMARY KEY AUTOINCREMENT, alert_id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO notification_feed VALUES (1, ?, ?, ?, ?, ?)",
            ("event:old", "event", "Old alert", "Evidence", NOW.isoformat()),
        )
    migrated = Store(path)
    try:
        assert inbox_page(migrated, now=NOW)["alerts"][0]["title"] == "Old alert"
        assert inbox_counts(migrated, NOW)["unread"] == 1
    finally:
        migrated.close()


def test_cli_inbox_never_initializes_aws(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aws_cost_agent.cli.AWS", lambda *a: pytest.fail("Must not initialize AWS"))
    assert main(["inbox", "list"]) == 0
    page = json.loads(capsys.readouterr().out)
    assert page["counts"]["total"] == 0
    local = Store("data/agent.sqlite3")
    alert = seed(local, 1)[0]
    local.close()
    assert (
        main(
            [
                "inbox",
                "update",
                "--sequence",
                str(alert["sequence"]),
                "--feed-id",
                page["feed_id"],
                "--action",
                "review",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["counts"]["reviewed"] == 1
    assert main(["inbox", "list", "--filter", "reviewed"]) == 0
    assert len(json.loads(capsys.readouterr().out)["alerts"]) == 1
