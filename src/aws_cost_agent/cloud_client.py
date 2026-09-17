"""IAM-authenticated access to the monitor; no public HTTP endpoint or stored API key."""

import json
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from botocore.config import Config as SDKConfig

from .aws import AWS
from .cloud_runtime import STATE_KEY
from .store import Store


@contextmanager
def cloud_store(config):
    aws = AWS(config)
    data = (
        aws.client("s3", config.cloud_region)
        .get_object(Bucket=config.cloud_bucket, Key=STATE_KEY, ExpectedBucketOwner=config.account_id)["Body"]
        .read()
    )
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "remote.sqlite3"
        path.write_bytes(data)
        store = Store(str(path))
        try:
            store.bind_account(config.account_id)
            yield store
        finally:
            store.close()


def invoke(config, event):
    aws = AWS(config)
    aws.sdk_config = SDKConfig(retries={"max_attempts": 0}, connect_timeout=10, read_timeout=260)
    response = aws.client("lambda", config.cloud_region).invoke(
        FunctionName=config.cloud_function,
        InvocationType="RequestResponse",
        Payload=json.dumps({**event, "account_id": config.account_id}).encode(),
    )
    payload = json.loads(response["Payload"].read())
    if response.get("FunctionError"):
        raise ValueError(
            "Cloud operation failed. Refresh to inspect the saved monitor status; check Lambda logs if needed."
        )
    if not payload.get("ok"):
        raise ValueError(payload.get("error", "Cloud operation did not complete"))
    return payload


def cloud_status(store, config):
    from .status import status_payload

    result = status_payload(store, config)
    monitoring = store.metadata("cloud_monitor") or {}
    checked = monitoring.get("checked_at")
    fresh = False
    if checked:
        fresh = timedelta(0) <= datetime.now(UTC) - datetime.fromisoformat(checked) < timedelta(minutes=15)
    errors = monitoring.get("errors", [])
    result["monitoring"] = {
        "mode": "cloud",
        "healthy": fresh and not errors,
        "checked_at": checked,
        "message": "; ".join(errors)
        if errors
        else ("Checking every five minutes in AWS" if fresh else "No recent cloud heartbeat"),
        "region": config.cloud_region,
        "function_name": config.cloud_function,
    }
    result["worker"] = {"running": False, "pid": None}
    result["notifications"]["delivery"] = "disabled"
    return result


def execute(args, config):
    from .analysis import render_report
    from .inbox import inbox_page

    if args.command in {"sync", "history"}:
        return json.dumps(invoke(config, {"action": "tick", "force": args.command == "sync"}))
    if args.command == "inbox" and args.inbox_action == "update":
        return json.dumps(
            invoke(
                config,
                {
                    "action": "inbox_update",
                    "sequence": args.sequence,
                    "feed_id": args.feed_id,
                    "operation": args.action,
                    "hours": args.hours,
                },
            )
        )
    if args.command not in {"status", "inbox", "alerts", "report", "outbox", "ask"}:
        raise ValueError(
            "This connection uses cloud monitoring. Local workers and email delivery are disabled."
        )
    with cloud_store(config) as store:
        if args.command == "status":
            return json.dumps(cloud_status(store, config))
        if args.command == "inbox":
            return json.dumps(inbox_page(store, args.filter, args.before, args.limit))
        if args.command == "alerts":
            return json.dumps(store.alerts_after(args.after, args.limit))
        if args.command == "outbox":
            return json.dumps(
                [
                    {"id": m["id"], "subject": m["subject"], "status": "email disabled"}
                    for m in store.messages()
                ]
            )
        snapshot = store.snapshot()
        if not snapshot:
            raise ValueError("The cloud monitor has not collected its first cost report yet.")
        if args.command == "report" and args.json:
            return json.dumps(snapshot)
        # Email and Bedrock are intentionally not activated by the monitoring deployment.
        return render_report(snapshot, store.events())
