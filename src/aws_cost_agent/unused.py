"""Track repeated evidence of inactivity; creation age alone never establishes disuse."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256

from .idle import idle_candidates


def collect_unused(provider, config):
    volumes, warnings = [], []
    if not config.demo:
        for region in dict.fromkeys(config.history_regions or [config.region]):
            try:
                volumes.extend(provider.unattached_volumes(region))
            except Exception as error:
                code = getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)
                warnings.append(
                    f"Unused EBS checks unavailable in {region} ({code}); monitoring duration resets."
                )
    return volumes, warnings


def track_unused(store, volumes, recommendations, config, account, now):
    """Call in the snapshot transaction. A missing finding or observation gap resets its clock."""
    aws_findings = idle_candidates(recommendations, replace(config, idle_monthly_savings=Decimal(0)), now)
    evidence = [
        {
            **r,
            "cost_alert_key": r["id"],
            "signal": "AWS repeatedly recommends stopping or deleting this resource",
        }
        for r in aws_findings
    ]
    # Prefer the direct state observation if both sources cover the same EBS volume.
    evidence.extend(volumes)
    previous = store.metadata("unused_observations") or {}
    current = {}
    for item in evidence:
        resource, region = item["resource_id"], item["region"]
        canonical = (
            resource.split(":", 5)[-1].removeprefix("volume/") if resource.startswith("arn:") else resource
        )
        key = sha256(f"{region}:{canonical}".encode()).hexdigest()[:24]
        old = previous.get(key)
        first = now
        if old and old["source"] == item["source"] and old.get("created_at") == item.get("created_at"):
            last = datetime.fromisoformat(old["last_checked"])
            # One delayed check is tolerated; a sleeping/offline Mac cannot accumulate idle days.
            if timedelta(0) <= now - last <= timedelta(hours=config.sync_hours * 2 + 1):
                first = datetime.fromisoformat(old["first_observed"])
        creator = store.creation_for(resource, region)
        if creator and first < datetime.fromisoformat(creator["time"].replace("Z", "+00:00")) <= now:
            first = now
        attachment = store.latest_volume_attachment(canonical, region)
        if attachment and first < datetime.fromisoformat(attachment.replace("Z", "+00:00")) <= now:
            first = now
        days = max(0, (now - first).days)
        finding = {
            **item,
            "id": key,
            "first_observed": first.isoformat(),
            "last_checked": now.isoformat(),
            "observed_days": days,
            "threshold_days": config.unused_after_days,
            "ready": days >= config.unused_after_days,
            "creator": creator["actor"] if creator else None,
            "creation_time": creator["time"] if creator else item.get("created_at"),
            "creation_event_id": creator["id"] if creator else None,
        }
        if key in current and current[key].get("cost_alert_key"):
            finding["cost_alert_key"] = current[key]["cost_alert_key"]
        current[key] = finding
    store.save_metadata("unused_observations", current)
    for finding in current.values():
        if not config.idle_alerts or not finding["ready"]:
            continue
        key = "unused:" + finding["id"]
        last = store.last_idle_notification(key)
        if last and now - datetime.fromisoformat(last) < timedelta(days=config.idle_reminder_days):
            continue
        creator = finding["creator"] or "Unavailable in collected CloudTrail history"
        saving = finding.get("monthly_savings")
        cost = f"AWS estimated saving: USD {saving}/month" if saving else "Potential saving: not yet measured"
        store.enqueue(
            f"idle:{key}:{now.isoformat()}",
            f"AWS resource unused at checks for {finding['observed_days']} days",
            f"Account: {account}\nResource: {finding['resource_id']}\nRegion: {finding['region']}\n"
            f"Creator AWS identity: {creator}\nCreated: {finding['creation_time'] or 'Unknown'}\n"
            f"Evidence: {finding['signal']}\nSource: {finding['source']}\n"
            f"Observation period: {finding['first_observed']} to {finding['last_checked']}\n"
            f"{cost}\n\n"
            "This is repeated sampled evidence, not proof of continuous inactivity between checks. "
            "A role or service identity does not identify a specific engineer. "
            "Confirm with the owner whether this resource is still needed, including backups and dependencies. "
            "No infrastructure changes have been made.",
        )
        store.record_idle_notification(key, now.isoformat())
        if finding.get("cost_alert_key"):
            # Do not emit a second cost-based reminder for this resource in the same sync.
            store.record_idle_notification(finding["cost_alert_key"], now.isoformat())
    return sorted(current.values(), key=lambda r: (-r["observed_days"], r["resource_id"]))
