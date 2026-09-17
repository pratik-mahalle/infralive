"""Local alert triage. Never consumes the desktop cursor or changes email delivery."""

from datetime import UTC, datetime, timedelta


def _now(now):
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("Inbox timestamps must include a timezone")
    return value.astimezone(UTC)


def _query():
    return """
        WITH inbox AS (
            SELECT f.*, s.read_at, s.reviewed_at, s.snoozed_until,
                CASE WHEN s.reviewed_at IS NOT NULL THEN 'reviewed'
                     WHEN s.snoozed_until > :now THEN 'snoozed'
                     ELSE 'open' END AS state,
                CASE WHEN s.read_at IS NULL OR
                    (s.snoozed_until <= :now AND s.read_at < s.snoozed_until)
                    THEN 1 ELSE 0 END AS unread
            FROM notification_feed f LEFT JOIN alert_inbox_state s USING (alert_id)
        )
    """


def inbox_counts(store, now=None):
    row = store.db.execute(
        _query()
        + """
        SELECT COUNT(*) AS total,
            COALESCE(SUM(state='open'), 0) AS open,
            COALESCE(SUM(state='snoozed'), 0) AS snoozed,
            COALESCE(SUM(state='reviewed'), 0) AS reviewed,
            COALESCE(SUM(state='open' AND unread=1), 0) AS unread
        FROM inbox
        """,
        {"now": _now(now).isoformat()},
    ).fetchone()
    return dict(row)


def inbox_page(store, state="open", before=0, limit=50, now=None):
    if state not in {"open", "snoozed", "reviewed"}:
        raise ValueError("Inbox filter must be open, snoozed or reviewed")
    if before < 0 or not 1 <= limit <= 100:
        raise ValueError("Inbox cursor must be nonnegative; limit must be 1–100")
    now = _now(now)
    rows = [
        dict(row)
        for row in store.db.execute(
            _query()
            + """
        SELECT * FROM inbox WHERE state=:state AND (:before=0 OR sequence<:before)
        ORDER BY sequence DESC LIMIT :limit
        """,
            {"now": now.isoformat(), "state": state, "before": before, "limit": limit + 1},
        )
    ]
    more = len(rows) > limit
    rows = rows[:limit]
    feed_id = store.notification_feed_id()
    for row in rows:
        row["unread"] = bool(row["unread"])
        row["feed_id"] = feed_id
    return {
        "feed_id": feed_id,
        "filter": state,
        "alerts": rows,
        "counts": inbox_counts(store, now),
        "next_before": rows[-1]["sequence"] if more else None,
    }


def update_inbox(store, sequence, feed_id, action, hours=24, now=None):
    if feed_id != store.notification_feed_id():
        raise ValueError("This alert belongs to another inbox. Refresh and try again.")
    if action not in {"read", "unread", "review", "reopen", "snooze"}:
        raise ValueError("Unknown inbox action")
    if action == "snooze" and not 1 <= hours <= 24 * 30:
        raise ValueError("Snooze duration must be between 1 hour and 30 days")
    now = _now(now)
    with store.transaction():
        row = store.db.execute(
            "SELECT alert_id FROM notification_feed WHERE sequence=?", (sequence,)
        ).fetchone()
        if not row:
            raise ValueError("Alert not found in this account")
        key = row[0]
        store.db.execute("INSERT OR IGNORE INTO alert_inbox_state (alert_id) VALUES (?)", (key,))
        if action in {"read", "unread"}:
            store.db.execute(
                "UPDATE alert_inbox_state SET read_at=? WHERE alert_id=?",
                (now.isoformat() if action == "read" else None, key),
            )
        elif action == "review":
            store.db.execute(
                "UPDATE alert_inbox_state SET reviewed_at=?, read_at=?, snoozed_until=NULL WHERE alert_id=?",
                (now.isoformat(), now.isoformat(), key),
            )
        elif action == "reopen":
            store.db.execute(
                "UPDATE alert_inbox_state SET reviewed_at=NULL, read_at=NULL, snoozed_until=NULL WHERE alert_id=?",
                (key,),
            )
        else:
            store.db.execute(
                "UPDATE alert_inbox_state SET reviewed_at=NULL, read_at=NULL, snoozed_until=? WHERE alert_id=?",
                ((now + timedelta(hours=hours)).isoformat(), key),
            )
    return {"sequence": sequence, "action": action, "counts": inbox_counts(store, now)}
