"""Compact, versioned local interface for the native menu bar companion."""

from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from .analysis import money
from .inbox import inbox_counts
from .locking import worker_status


def status_payload(store, config):
    snapshot = store.snapshot()
    daily = defaultdict(Decimal)
    if snapshot:
        for row in snapshot.get("daily_costs", []):
            if row.get("record_type") in {"Credit", "Refund"}:
                continue
            daily[row["day"]] += Decimal(row["amount"])
    messages = store.messages()
    compact = {k: v for k, v in snapshot.items() if k != "daily_costs"} if snapshot else None
    return {
        "schema_version": 1,
        "notification_cursor": store.notification_cursor(),
        "notification_feed_id": store.notification_feed_id(),
        "inbox_summary": inbox_counts(store),
        "demo": config.demo,
        "snapshot": compact,
        "daily_totals": [{"day": day, "amount": money(amount)} for day, amount in sorted(daily.items())][
            -14:
        ],
        "events": store.events(20, include_routine=False),
        "all_events": store.events(20),
        "activity": store.metadata("history_status"),
        "notifications": {
            "pending": sum(m["status"] == "pending" for m in messages),
            "failed": sum(m["status"] == "pending" and m["attempts"] > 0 for m in messages),
            "sent": sum(m["status"] == "sent" for m in messages),
            "previewed": sum(m["status"] == "previewed" for m in messages),
            "delivery": config.delivery,
        },
        "worker": worker_status(config.database),
        "paths": {
            "database": str(Path(config.database).resolve()),
            "email_previews": str(Path(config.outbox_dir).resolve()),
        },
    }
