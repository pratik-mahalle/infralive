"""Alert on fresh AWS idle recommendations, never infer idle from resource age."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256

from .analysis import money


def idle_candidates(recommendations, config, now):
    candidates = []
    for r in recommendations:
        # These AWS Cost Optimization Hub actions explicitly target idle/unused resources.
        if r.get("action_type") not in {"Stop", "Delete"} or r.get("currency") != "USD":
            continue
        try:
            savings = Decimal(r["monthly_savings"])
            refreshed = datetime.fromisoformat(r["last_refresh"].replace("Z", "+00:00"))
            if refreshed.tzinfo is None:
                continue
        except (KeyError, ValueError, TypeError, AttributeError, InvalidOperation):
            continue
        if not savings.is_finite() or savings <= 0 or savings < config.idle_monthly_savings:
            continue
        if not timedelta(0) <= now - refreshed <= timedelta(hours=72):
            continue
        resource = r.get("resource_id")
        if not resource or resource == "Unknown":
            continue
        key = sha256(f"{r.get('region')}:{resource}".encode()).hexdigest()[:24]
        candidates.append(
            {
                "id": key,
                "recommendation_id": r["id"],
                "resource_id": resource,
                "resource_type": r.get("resource_type", "AWS resource"),
                "region": r.get("region", "unknown"),
                "action": r["action_type"],
                "monthly_savings": money(savings),
                "currency": "USD",
                "evidence_timestamp": refreshed.isoformat(),
                "source": r.get("source", "AWS Cost Optimization Hub"),
            }
        )
    return candidates


def queue_idle_alerts(store, candidates, config, account, now=None):
    if not config.idle_alerts:
        return
    now = now or datetime.now(UTC)
    for c in candidates:
        previous = store.last_idle_notification(c["id"])
        if previous and now - datetime.fromisoformat(previous) < timedelta(days=config.idle_reminder_days):
            continue
        creator = store.creation_for(c["resource_id"], c["region"])
        attribution = (
            f"Creator AWS identity: {creator['actor']}\nCreated: {creator['time']}\n"
            if creator
            else "Creator AWS identity: unavailable in collected CloudTrail history\n"
        )
        store.enqueue(
            f"idle:{c['id']}:{now.isoformat()}",
            "AWS idle resource: avoidable cost detected",
            f"Account: {account}\nResource: {c['resource_id']}\nRegion: {c['region']}\n"
            + attribution
            + f"Estimated avoidable cost: USD {c['monthly_savings']}/month\n"
            f"AWS recommendation: {c['action']}\nSource: {c['source']}\n"
            f"Evidence refreshed: {c['evidence_timestamp']}\nRecommendation: {c['recommendation_id']}\n\n"
            "AWS identified this resource as idle or unused. This is an estimated saving, not an exact billed charge. "
            "Confirm the owner, backups, dependencies and disaster-recovery needs before stopping or deleting it. "
            "No infrastructure changes have been made.",
        )
        store.record_idle_notification(c["id"], now.isoformat())
