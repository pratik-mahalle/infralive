"""Scheduled, single-writer AWS monitor. Email delivery is deliberately disabled."""

import json
import os
import sqlite3
import tempfile
import time
import uuid
from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from .aws import AWS
from .config import Config
from .history import collect_history
from .inbox import update_inbox
from .store import Store
from .worker import poll, sync

STATE_KEY = "state/agent.sqlite3"
CONFIG_KEY = "config/monitor.json"


def runtime_config(data, directory, account):
    allowed = {f.name for f in fields(Config)}
    config = Config(**{k: v for k, v in data.items() if k in allowed})
    if config.account_id != account:
        raise ValueError("Cloud configuration account mismatch")
    for key in ("anomaly_dollars", "anomaly_percent", "monthly_budget", "idle_monthly_savings"):
        setattr(config, key, Decimal(str(getattr(config, key))))
    config.database = str(Path(directory) / "agent.sqlite3")
    config.outbox_dir = str(Path(directory) / "email-preview")
    config.profile = None
    config.role_arn = config.external_id = config.model_id = ""
    config.cloud_bucket = config.cloud_function = ""
    config.demo = False
    config.delivery = "preview"
    config.sender = ""
    config.recipients = []
    return config


def tick(store, provider, config, force=False, now=None):
    now = now or datetime.now(UTC)
    failures = []
    if force or now.timestamp() >= (store.metadata("cloud_next_sync") or 0):
        try:
            sync(store, provider, config, now.date())
            with store.transaction():
                store.save_metadata("cloud_next_sync", now.timestamp() + config.sync_hours * 3600)
                store.save_metadata("cloud_cost_error", None)
        except Exception as error:
            code = getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)
            with store.transaction():
                store.save_metadata("cloud_next_sync", now.timestamp() + 300)
                store.save_metadata("cloud_cost_error", f"Cost collection failed ({code})")
    if store.metadata("cloud_cost_error"):
        failures.append(store.metadata("cloud_cost_error"))
    try:
        history = collect_history(store, provider, config, now)
        failures.extend(history.get("warnings", []))
        poll(store, provider, config)
    except Exception as error:
        failures.append(f"Activity collection failed ({type(error).__name__})")
    result = {"checked_at": now.isoformat(), "errors": failures}
    with store.transaction():
        store.save_metadata("cloud_monitor", result)
    return result


def handler(event, context):
    bucket, account, table = (os.environ[k] for k in ("STATE_BUCKET", "ACCOUNT_ID", "LOCK_TABLE"))
    action = event.get("action", "tick")
    if action not in {"tick", "inbox_update", "health"}:
        raise ValueError("Unsupported monitor action")
    if event.get("account_id", account) != account:
        raise ValueError("Account mismatch")
    if action == "health":
        actual = boto3.client("sts").get_caller_identity()["Account"]
        if actual != account:
            raise ValueError("Execution role account mismatch")
        return {"ok": True, "account_id": actual}
    token = str(uuid.uuid4())
    lock = boto3.client("dynamodb")
    remaining = context.get_remaining_time_in_millis() // 1000
    try:
        lock.put_item(
            TableName=table,
            Item={
                "lock_id": {"S": "state"},
                "token": {"S": token},
                "expires_at": {"N": str(int(time.time()) + remaining + 30)},
            },
            ConditionExpression="attribute_not_exists(lock_id) OR expires_at < :now",
            ExpressionAttributeValues={":now": {"N": str(int(time.time()))}},
        )
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            if action == "tick":
                return {"ok": True, "skipped": "Another check is running"}
            return {"ok": False, "error": "The cloud monitor is updating its data. Try again shortly."}
        raise
    try:
        s3 = boto3.client("s3")
        with tempfile.TemporaryDirectory() as directory:
            payload = s3.get_object(Bucket=bucket, Key=CONFIG_KEY, ExpectedBucketOwner=account)["Body"].read()
            config = runtime_config(json.loads(payload), directory, account)
            # Never initialize an empty replacement when the durable state cannot be read.
            Path(config.database).write_bytes(
                s3.get_object(Bucket=bucket, Key=STATE_KEY, ExpectedBucketOwner=account)["Body"].read()
            )
            store = Store(config.database)
            try:
                store.bind_account(account)
                if action == "inbox_update":
                    result = update_inbox(
                        store,
                        int(event["sequence"]),
                        event["feed_id"],
                        event["operation"],
                        int(event.get("hours", 24)),
                    )
                else:
                    result = tick(store, AWS(config), config, bool(event.get("force", False)))
                backup = str(Path(directory) / "durable.sqlite3")
                with sqlite3.connect(backup) as dest:
                    store.db.backup(dest)
                s3.put_object(
                    Bucket=bucket,
                    Key=STATE_KEY,
                    Body=Path(backup).read_bytes(),
                    ExpectedBucketOwner=account,
                    ContentType="application/vnd.sqlite3",
                    ServerSideEncryption="AES256",
                )
            finally:
                store.close()
        if action == "tick" and result.get("errors"):
            raise RuntimeError("Cloud monitoring check incomplete; see saved monitoring status")
        return {"ok": True, "result": result}
    finally:
        lock.delete_item(
            TableName=table,
            Key={"lock_id": {"S": "state"}},
            ConditionExpression="#token=:token",
            ExpressionAttributeNames={"#token": "token"},
            ExpressionAttributeValues={":token": {"S": token}},
        )
