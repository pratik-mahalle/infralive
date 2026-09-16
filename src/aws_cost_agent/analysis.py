from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median


def money(value):
    rounded = Decimal(value).quantize(Decimal("0.01"))
    return "0.00" if rounded == 0 else str(rounded)


def analyze(rows, today: date, config):
    """Compare a lagged day to three matching weekdays; never compare partial today."""
    target = today - timedelta(days=2)
    by_day = defaultdict(lambda: defaultdict(Decimal))
    billing_days = set()
    month = defaultdict(Decimal)
    adjustments = defaultdict(Decimal)
    currencies = {r["currency"] for r in rows}
    if len(currencies) > 1:
        raise ValueError("Mixed billing currencies cannot be summed")
    currency = next(iter(currencies), "USD")
    provisional = False
    for r in rows:
        day = date.fromisoformat(r["day"])
        amount = Decimal(r["amount"])
        if not amount.is_finite():
            raise ValueError("Billing amounts must be finite")
        if day >= today:
            continue
        billing_days.add(day)
        current_month = day.month == today.month and day.year == today.year
        if current_month:
            provisional |= r.get("estimated", False)
        if r.get("record_type") in {"Credit", "Refund"}:
            if current_month:
                adjustments[r["record_type"]] += amount
            continue
        key = (r["service"], r["region"])
        by_day[day][key] += amount
        if current_month:
            month[r["service"]] += amount
            provisional |= r.get("estimated", False)
    baseline_days = [target - timedelta(days=n) for n in (7, 14, 21)]
    anomalies = []
    # Missing dates are unknown, not zero. A missing service on a present date is zero.
    if target in by_day and all(d in by_day for d in baseline_days):
        for (service, region), actual in by_day[target].items():
            baseline = median([by_day[d].get((service, region), Decimal(0)) for d in baseline_days])
            delta = actual - baseline
            percent = delta / baseline * 100 if baseline > 0 else None
            if (
                delta >= config.anomaly_dollars
                and delta > 0
                and (percent is None or percent >= config.anomaly_percent)
            ):
                anomalies.append(
                    {
                        "id": f"spend:{target}:{service}:{region}",
                        "day": str(target),
                        "service": service,
                        "region": region,
                        "actual": money(actual),
                        "baseline": money(baseline),
                        "increase": money(delta),
                        "percent": money(percent) if percent is not None else None,
                        "currency": currency,
                        "baseline_days": [str(d) for d in baseline_days],
                        "explanation": "Charges before credits/refunds versus median of the previous three matching weekdays; billing may be revised.",
                    }
                )
    return {
        "month_to_date": money(sum(month.values(), Decimal(0)) + sum(adjustments.values(), Decimal(0))),
        "spend_before_credits": money(sum(month.values(), Decimal(0))),
        "credits": money(adjustments["Credit"]),
        "refunds": money(adjustments["Refund"]),
        "cost_basis": "Charges before credits and refunds; net balance shown separately",
        "period_start": str(today.replace(day=1)),
        "period_end_exclusive": str(today),
        "currency": currency,
        "cost_metric": "UnblendedCost",
        "billing_provisional": provisional,
        "billing_through": str(max(billing_days)) if billing_days else None,
        "analyzed_day": str(target),
        "anomaly_coverage": "available"
        if target in by_day and all(d in by_day for d in baseline_days)
        else "insufficient history",
        "top_services": [
            {"service": s, "amount": money(a)}
            for s, a in sorted(month.items(), key=lambda x: x[1], reverse=True)
        ],
        "anomalies": sorted(anomalies, key=lambda x: Decimal(x["increase"]), reverse=True),
    }


def render_report(snapshot, events=None):
    a = snapshot["analysis"]
    unit = a["currency"]
    lines = [
        "AWS COST AGENT" + (" — DEMO / SYNTHETIC DATA" if snapshot.get("demo") else ""),
        f"Account: {snapshot['account_id']} | Collected: {snapshot['collected_at']}",
        f"Billing through: {a['billing_through']} | Metric: {a['cost_metric']}",
        f"Reported month to date, after credits/refunds: {unit} {a['month_to_date']} (excludes today)",
    ]
    if "spend_before_credits" in a:
        lines += [
            f"Charges before credits/refunds: {unit} {a['spend_before_credits']}",
            f"Credits: {unit} {a['credits']} | Refunds: {unit} {a['refunds']}",
            f"Period: {a['period_start']} to {a['period_end_exclusive']} (end exclusive, UTC). All regions in this account.",
        ]
    if snapshot.get("forecast"):
        f = snapshot["forecast"]
        lines += [f"Estimated month total: {unit} {f['month_total']} ({f['method']})"]
    if a["billing_provisional"]:
        lines += ["Billing is provisional and may be revised by AWS."]
    lines += ["", "WHERE THE MONEY GOES"]
    lines += [f"  {x['service']}: {unit} {x['amount']}" for x in a["top_services"]]
    lines += ["", f"SPENDING CHANGES — {a['analyzed_day']}"]
    for x in a["anomalies"]:
        pct = f"{x['percent']}%" if x["percent"] else "new spend"
        lines += [
            f"  {x['service']} / {x['region']}: +{unit} {x['increase']} ({pct})",
            f"    Actual {x['actual']}; baseline {x['baseline']}. Evidence: {x['id']}",
        ]
    if not a["anomalies"]:
        lines += [f"  No threshold breaches found. Coverage: {a['anomaly_coverage']}."]
    lines += ["", "SAVINGS TO REVIEW"]
    for idle in snapshot.get("idle_alerts", []):
        lines += [
            f"  IDLE RESOURCE: {idle['resource_id']} — estimated USD {idle['monthly_savings']}/month avoidable cost."
        ]
    for r in snapshot["recommendations"][:10]:
        lines += [
            f"  {r['action']} — {r['resource_id']} ({r['region']})",
            f"    Estimated {r['currency']} {r['monthly_savings']}/month; effort: {r['effort']}; "
            f"restart required: {r['restart_needed']}",
            f"    Evidence: {r['id']} | {r['source']}",
        ]
    if not snapshot["recommendations"]:
        lines += ["  No recommendations available; see coverage warnings below."]
    for lead in snapshot.get("review_leads", []):
        lines += [
            f"  REVIEW PRIORITY: {lead['title']} — {lead['currency']} {lead['period_spend']} in service charges this month.",
            f"    {lead['detail']}",
            "    Potential savings have not been measured; this is not an AWS idle-resource finding.",
        ]
    lines += [
        "  Savings are estimates, may overlap, and are not summed. Review workload requirements before acting."
    ]
    if events:
        lines += ["", "RECENT RESOURCE CHANGES"]
        for e in events[:10]:
            lines += [
                f"  {e['time']} | {e['action']} | {', '.join(e['resource_ids'])}",
                f"    Actor: {e['actor']} | Owner: {e['owner']} | Evidence: {e['id']}",
            ]
    if snapshot.get("warnings"):
        lines += ["", "COVERAGE / WARNINGS"] + [f"  {w}" for w in snapshot["warnings"]]
    lines += ["", "Infrastructure changes are candidate explanations, not proof of a billing cause."]
    return "\n".join(lines) + "\n"
