"""CloudTrail history backfill and polling, independent of an EventBridge deployment."""

import json
from datetime import UTC, datetime, timedelta

from .auth import requires_sign_in
from .events import ROUTINE_ACTIONS, clean, normalize_event, render_event
from .locking import worker_lock
from .store import now_iso


def collect_history(store, provider, config, now=None):
    if config.demo:
        return {"mode": "demo", "regions": [], "warnings": []}
    try:
        with worker_lock(config.database + ".history"):
            return _collect_history(store, provider, config, now)
    except ValueError as error:
        if "already running" not in str(error):
            raise
        return store.metadata("history_status") or {
            "mode": "CloudTrail event history",
            "regions": [],
            "warnings": ["Another history check is in progress."],
        }


def _collect_history(store, provider, config, now=None):
    now = now or datetime.now(UTC)
    account = provider.account_id()
    store.bind_account(account)
    regions = config.history_regions or [config.region]
    results, warnings = [], []
    for region in regions:
        key = "history:" + region
        state = store.metadata(key) or {}
        baseline = state.get("baseline", now.isoformat())
        start = state.get("start") or (now - timedelta(days=7)).isoformat()
        end = state.get("end") or now.isoformat()
        token = state.get("token")
        if datetime.fromisoformat(start) < now - timedelta(days=90):
            start, end, token = (now - timedelta(days=90)).isoformat(), now.isoformat(), None
        initial = not state.get("backfilled", False)
        count = 0
        try:
            # Persist a fixed window and page token. Busy accounts continue on the next poll.
            for _ in range(10):
                page = provider.history_page(region, start, end, token)
                events = []
                for item in page.get("Events", []):
                    detail = json.loads(item["CloudTrailEvent"])
                    if detail.get("eventType", "AwsApiCall") != "AwsApiCall":
                        continue
                    envelope = {
                        "detail-type": "AWS API Call via CloudTrail",
                        "account": account,
                        "region": region,
                        "detail": detail,
                    }
                    event = normalize_event(envelope, account, include_changes=True)
                    if not event:
                        continue
                    if event["resource_ids"] == ["ID unavailable"]:
                        names = [
                            clean(r["ResourceName"])
                            for r in item.get("Resources", [])
                            if r.get("ResourceName")
                        ]
                        if names:
                            event["resource_ids"] = names[:20]
                    event["source"] = "CloudTrail event history"
                    event["historical"] = initial
                    events.append(event)
                next_token = page.get("NextToken")
                with store.transaction():
                    for event in events:
                        if store.add_event(event):
                            count += 1
                            # Backfills are display-only. Only new creation calls after enrollment notify.
                            if (
                                not initial
                                and config.creation_alerts
                                and event["change_kind"] == "creation"
                                and (config.routine_creation_alerts or event["action"] not in ROUTINE_ACTIONS)
                                and datetime.fromisoformat(event["time"].replace("Z", "+00:00"))
                                >= datetime.fromisoformat(baseline)
                            ):
                                store.enqueue(
                                    event["id"],
                                    f"AWS resource change: {event['service']} / {event['action']}",
                                    render_event(event),
                                )
                    state = {
                        "baseline": baseline,
                        "backfilled": not bool(next_token) or not initial,
                        "start": start
                        if next_token
                        else max(
                            datetime.fromisoformat(end) - timedelta(minutes=15), now - timedelta(days=90)
                        ).isoformat(),
                        "end": end if next_token else None,
                        "token": next_token,
                    }
                    store.save_metadata(key, state)
                token = next_token
                if not token:
                    break
            results.append(
                {"region": region, "added": count, "backfill_pending": bool(token), "checked_at": now_iso()}
            )
        except Exception as error:
            if requires_sign_in(error):
                raise
            code = getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)
            # Invalid pagination tokens restart the same window on the next poll; IDs deduplicate.
            if code == "InvalidNextTokenException":
                state["token"] = None
                with store.transaction():
                    store.save_metadata(key, state)
            warnings.append(
                f"Activity history in {region} could not be read ({code}). Requires cloudtrail:LookupEvents."
            )
    result = {
        "mode": "CloudTrail event history",
        "regions": results,
        "warnings": warnings,
        "lookback_days": 7,
        "poll_minutes": 5,
        "checked_at": now_iso(),
    }
    with store.transaction():
        store.save_metadata("history_status", result)
    return result
