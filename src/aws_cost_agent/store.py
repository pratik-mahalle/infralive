"""SQLite snapshot, event and transactional email outbox persistence."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

from .events import ROUTINE_ACTIONS


def now_iso():
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, time TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox (
                id TEXT PRIMARY KEY, subject TEXT NOT NULL, body TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT, created_at TEXT NOT NULL, delivered_at TEXT);
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notification_feed (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
                body TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS idle_notifications (
                resource_key TEXT PRIMARY KEY, last_notified TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS alert_inbox_state (
                alert_id TEXT PRIMARY KEY, read_at TEXT, reviewed_at TEXT, snoozed_until TEXT);
        """)
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO metadata VALUES ('notification_feed_id', ?)", (str(uuid.uuid4()),)
            )

    def close(self):
        self.db.close()

    def bind_account(self, account):
        old = self.db.execute("SELECT value FROM metadata WHERE key='account' ").fetchone()
        if old and old[0] != account:
            raise ValueError("This database belongs to a different AWS account. Use another database path.")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('account', ?)", (account,))

    @contextmanager
    def transaction(self):
        with self.db:
            yield self

    def save_snapshot(self, snapshot):
        self.db.execute("INSERT OR REPLACE INTO snapshots VALUES (1, ?)", (json.dumps(snapshot),))

    def snapshot(self):
        row = self.db.execute("SELECT payload FROM snapshots WHERE id=1").fetchone()
        return json.loads(row[0]) if row else None

    def metadata(self, key):
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_metadata(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?)", (key, json.dumps(value)))

    def has_event(self, key):
        return self.db.execute("SELECT 1 FROM events WHERE id=?", (key,)).fetchone() is not None

    def add_event(self, event):
        cursor = self.db.execute(
            "INSERT OR IGNORE INTO events VALUES (?, ?, ?)", (event["id"], event["time"], json.dumps(event))
        )
        return cursor.rowcount == 1

    def events(self, limit=50, include_routine=True):
        where = (
            ""
            if include_routine
            else " WHERE json_extract(payload, '$.action') NOT IN ("
            + ",".join("?" for _ in ROUTINE_ACTIONS)
            + ")"
        )
        args = [limit] if include_routine else [*sorted(ROUTINE_ACTIONS), limit]
        return [
            json.loads(r[0])
            for r in self.db.execute(
                "SELECT payload FROM events" + where + " ORDER BY time DESC LIMIT ?", args
            )
        ]

    def enqueue(self, key, subject, body):
        self.db.execute(
            "INSERT OR IGNORE INTO outbox (id,subject,body,created_at) VALUES (?,?,?,?)",
            (key, subject, body, now_iso()),
        )
        kind = key.split(":", 1)[0]
        if kind in {"event", "spend", "budget", "idle"}:
            self.db.execute(
                "INSERT OR IGNORE INTO notification_feed (alert_id,kind,title,body,created_at) VALUES (?,?,?,?,?)",
                (key, kind, subject, body, now_iso()),
            )

    def creation_for(self, resource, region):
        # Only APIs whose normalized IDs identify the newly created resource, never related ARNs.
        service, action, identity = "ec2", "CreateVolume", resource
        if resource.startswith("arn:"):
            parts = resource.split(":", 5)
            if len(parts) != 6 or parts[3] != region:
                return None
            service, identity = parts[2], parts[5]
            account = self.db.execute("SELECT value FROM metadata WHERE key='account'").fetchone()
            if not account or parts[4] != account[0]:
                return None
            if service == "ec2":
                identity = identity.split("/")[-1]
            elif service == "lambda":
                action, identity = "CreateFunction20150331", resource
            elif service == "rds" and identity.startswith(("db:", "cluster:")):
                action = "CreateDBInstance" if identity.startswith("db:") else "CreateDBCluster"
                identity = identity.split(":", 1)[1]
            else:
                return None
        if service == "ec2":
            if identity.startswith("vol-"):
                action = "CreateVolume"
            elif identity.startswith("i-"):
                action = "RunInstances"
            else:
                return None
        row = self.db.execute(
            "SELECT e.payload FROM events e, json_each(e.payload, '$.resource_ids') r "
            "WHERE json_extract(e.payload, '$.region')=? "
            "AND json_extract(e.payload, '$.service')=? "
            "AND json_extract(e.payload, '$.action') IN (?, ?) AND r.value IN (?, ?) "
            "ORDER BY e.time DESC LIMIT 1",
            (
                region,
                service,
                action,
                "CreateFunction" if service == "lambda" else action,
                resource,
                identity,
            ),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def latest_volume_attachment(self, resource, region):
        row = self.db.execute(
            "SELECT e.time FROM events e, json_each(e.payload, '$.resource_ids') r "
            "WHERE json_extract(e.payload, '$.region')=? "
            "AND json_extract(e.payload, '$.service')='ec2' "
            "AND json_extract(e.payload, '$.action')='AttachVolume' AND r.value=? "
            "ORDER BY e.time DESC LIMIT 1",
            (region, resource),
        ).fetchone()
        return row[0] if row else None

    def notification_cursor(self):
        return self.db.execute("SELECT COALESCE(MAX(sequence),0) FROM notification_feed").fetchone()[0]

    def notification_feed_id(self):
        return self.db.execute("SELECT value FROM metadata WHERE key='notification_feed_id'").fetchone()[0]

    def alerts_after(self, after, limit=100):
        if after < 0 or not 1 <= limit <= 100:
            raise ValueError("Alert cursor must be nonnegative; limit must be 1–100")
        rows = [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM notification_feed WHERE sequence>? ORDER BY sequence LIMIT ?", (after, limit)
            )
        ]
        return {"alerts": rows, "next_cursor": rows[-1]["sequence"] if rows else after}

    def last_idle_notification(self, key):
        row = self.db.execute(
            "SELECT last_notified FROM idle_notifications WHERE resource_key=?", (key,)
        ).fetchone()
        return row[0] if row else None

    def record_idle_notification(self, key, timestamp):
        self.db.execute("INSERT OR REPLACE INTO idle_notifications VALUES (?, ?)", (key, timestamp))

    def messages(self, pending=False):
        query = "SELECT * FROM outbox" + (" WHERE status='pending'" if pending else "")
        return [dict(r) for r in self.db.execute(query + " ORDER BY created_at")]

    def delivered(self, key, status):
        with self.db:
            self.db.execute(
                "UPDATE outbox SET status=?, delivered_at=?, error=NULL WHERE id=?", (status, now_iso(), key)
            )

    def failed(self, key, error):
        with self.db:
            self.db.execute("UPDATE outbox SET attempts=attempts+1,error=? WHERE id=?", (error, key))
