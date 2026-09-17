import json
import logging
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .analysis import analyze, money, render_report
from .auth import requires_sign_in
from .aws import utc_today
from .events import ROUTINE_ACTIONS, normalize_event, render_event
from .history import collect_history
from .idle import idle_candidates, queue_idle_alerts
from .notifications import deliver
from .savings import recommendation_status, review_leads
from .store import now_iso
from .unused import collect_unused, track_unused

logger = logging.getLogger(__name__)


def sync(store, provider, config, today=None):
    today = today or utc_today()
    account = provider.account_id()
    store.bind_account(account)
    # A failed cost request must not replace a successful snapshot with zeros.
    rows = provider.costs(today, account)
    if not rows:
        raise ValueError("AWS returned no cost rows; previous snapshot retained")
    analysis = analyze(rows, today, config)
    warnings, forecast, recommendations = [], None, []
    if not analysis["billing_through"] or analysis["billing_through"] < str(today - timedelta(days=1)):
        warnings.append(
            "Latest billing day is missing; reported totals and forecast may understate spending."
        )
    try:
        forecast = provider.forecast(today, account)
        if forecast["currency"] != analysis["currency"]:
            raise ValueError("Forecast currency differs from billing currency")
        forecast["month_total"] = money(
            Decimal(analysis["spend_before_credits"]) + Decimal(forecast["remaining"])
        )
    except Exception as error:
        forecast = None
        warnings.append(
            f"Forecast unavailable ({type(error).__name__}); AWS may need more history or permissions."
        )
    try:
        recommendations = provider.recommendations(account)
        savings_status = recommendation_status()
    except Exception as error:
        savings_status = recommendation_status(error)
        warnings.append(savings_status["message"])
    if not config.queues and not config.demo:
        warnings.append(
            "Resource activity uses CloudTrail history polling. EventBridge queues are optional for faster delivery."
        )
    observed_at = datetime.now(UTC)
    idle = idle_candidates(recommendations, config, observed_at)
    volumes, unused_warnings = collect_unused(provider, config)
    warnings.extend(unused_warnings)
    if savings_status["state"] != "available":
        unused_warnings.append(savings_status["message"])
    snapshot = {
        "account_id": account,
        "collected_at": now_iso(),
        "demo": config.demo,
        "analysis": analysis,
        "forecast": forecast,
        "recommendations": recommendations,
        "savings_status": savings_status,
        "review_leads": review_leads(analysis),
        "idle_alerts": idle,
        "warnings": warnings,
        "daily_costs": rows,
    }
    with store.transaction():
        snapshot["unused_resources"] = track_unused(
            store, volumes, recommendations, config, account, observed_at
        )
        snapshot["unused_monitoring"] = {
            "threshold_days": config.unused_after_days,
            "regions": config.history_regions or [config.region],
            "enabled": config.idle_alerts,
            "warnings": unused_warnings,
        }
        store.save_snapshot(snapshot)
        queue_idle_alerts(store, idle, config, account, observed_at)
        for anomaly in analysis["anomalies"]:
            store.enqueue(
                anomaly["id"],
                f"AWS spending increase: {anomaly['service']}",
                f"Account: {account}\nBasis: charges before credits and refunds\n"
                + json.dumps(anomaly, indent=2),
            )
        if forecast and config.monthly_budget > 0 and analysis["currency"] == "USD":
            if Decimal(forecast["month_total"]) > config.monthly_budget:
                store.enqueue(
                    f"budget:{today:%Y-%m}",
                    "AWS forecast exceeds monthly budget",
                    f"Account: {account}\nForecast: USD {forecast['month_total']}\n"
                    f"Budget: USD {config.monthly_budget}\nBasis: before credits and refunds. This is an estimate, not a billed charge.",
                )
    return snapshot


def digest(store, today=None):
    snapshot = store.snapshot()
    if not snapshot:
        raise ValueError("No data yet. Run sync first.")
    key = f"digest:{today or utc_today()}"
    with store.transaction():
        store.enqueue(key, "AWS daily spending report", render_report(snapshot, store.events()))


def ingest(store, provider, config, envelope):
    account = provider.account_id()
    store.bind_account(account)
    event = normalize_event(envelope, account)
    if event is None or store.has_event(event["id"]):
        return False
    try:
        event = provider.enrich_event(event)
    except Exception as error:
        event["enrichment_warning"] = f"Metadata or pricing unavailable ({type(error).__name__})"
    with store.transaction():
        if not store.add_event(event):
            return False
        if config.creation_alerts and (
            config.routine_creation_alerts or event["action"] not in ROUTINE_ACTIONS
        ):
            store.enqueue(
                event["id"],
                f"AWS resource change: {event['service']} / {event['action']}",
                render_event(event),
            )
    return True


def poll(store, provider, config):
    count = 0
    for region, queue in config.queues.items():
        try:
            messages = provider.receive(region, queue)
        except Exception as error:
            if requires_sign_in(error):
                raise
            logger.error("Queue polling failed in %s (%s)", region, type(error).__name__)
            continue
        for message in messages:
            try:
                envelope = json.loads(message["Body"])
                count += ingest(store, provider, config, envelope)
                # Persist event and email intent before acknowledging SQS delivery.
                provider.acknowledge(region, queue, message["ReceiptHandle"])
            except Exception as error:
                if requires_sign_in(error):
                    raise
                logger.warning(
                    "Message processing failed (%s); left for retry / dead-letter queue", type(error).__name__
                )
    return count


def run(store, provider, config, once=False):
    next_sync = 0.0
    next_history = 0.0
    while True:
        if time.monotonic() >= next_sync:
            try:
                sync(store, provider, config)
                next_sync = time.monotonic() + config.sync_hours * 3600
                logger.info("Cost snapshot updated")
            except Exception as error:
                if requires_sign_in(error):
                    raise
                logger.error("Cost sync failed (%s); previous snapshot retained", type(error).__name__)
                next_sync = time.monotonic() + 300
                if once:
                    raise
        snapshot = store.snapshot()
        now = datetime.now(UTC)
        if (
            snapshot
            and now.hour >= config.digest_hour_utc
            and snapshot["collected_at"][:10] == str(now.date())
        ):
            digest(store)
        if config.demo:
            ingest(store, provider, config, provider.event())
        else:
            if time.monotonic() >= next_history:
                try:
                    collect_history(store, provider, config)
                except Exception as error:
                    if requires_sign_in(error):
                        raise
                    logger.warning("Activity history unavailable (%s)", type(error).__name__)
                next_history = time.monotonic() + 300
            poll(store, provider, config)
        deliver(store, config, provider)
        if once:
            return
        time.sleep(10 if config.queues else 30)
