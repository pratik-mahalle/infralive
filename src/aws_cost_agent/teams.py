"""Billing-tag attribution. Project and owner are separate views of the same charges."""

from collections import defaultdict
from decimal import Decimal

from .analysis import money


def summarize_group(rows, total, currency):
    groups = defaultdict(Decimal)
    for row in rows:
        amount = Decimal(row["amount"])
        if not amount.is_finite() or row["currency"] != currency:
            raise ValueError("Invalid team billing amounts or mixed currencies")
        groups[row["value"]] += amount
    if money(sum(groups.values(), Decimal(0))) != total:
        raise ValueError("Tag totals differ from the billing snapshot; refresh to reconcile")
    # Empty tag values stay distinguishable from a real tag whose value is 'Unassigned'.
    groups.setdefault("", Decimal(0))
    rounded = {key: Decimal(money(value)) for key, value in groups.items()}
    difference = Decimal(total) - sum(rounded.values(), Decimal(0))
    # Distribute fractional-cent rounding so visible rows reconcile to the displayed total.
    step = Decimal("0.01") if difference > 0 else Decimal("-0.01")
    order = sorted(groups, key=lambda key: (groups[key] - rounded[key], key), reverse=difference > 0)
    for key in order[: int(abs(difference) / Decimal("0.01"))]:
        rounded[key] += step
    return [
        {"id": key, "name": key or "Unassigned", "unassigned": key == "", "amount": money(rounded[key])}
        for key, value in sorted(groups.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def collect_teams(provider, config, today, account, analysis):
    total, currency = analysis["spend_before_credits"], analysis["currency"]
    try:
        tags = provider.allocation_tags()
        failure = None
    except Exception as error:
        tags = {}
        failure = getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)
    result = {"currency": currency, "total": total, "basis": "Before credits and refunds", "dimensions": []}
    for dimension, key in (("project", config.project_tag), ("owner", config.owner_tag)):
        row = {"id": dimension, "tag_key": key, "state": "available", "message": None}
        try:
            if failure:
                raise ValueError(f"Billing tag access unavailable ({failure}).")
            if tags.get(key) != "Active":
                row["state"] = "not_active"
                raise ValueError(
                    f"'{key}' is not an active cost-allocation tag. Apply it to resources, then activate it in AWS Billing. Data may take time to appear."
                )
            row["groups"] = summarize_group(provider.team_costs(today, account, key), total, currency)
        except Exception as error:
            if row["state"] == "available":
                row["state"] = "unavailable"
            code = getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)
            row["message"] = (
                str(error) if isinstance(error, ValueError) else f"Tag allocation unavailable ({code})."
            )
            row["groups"] = [{"id": "", "name": "Unassigned", "unassigned": True, "amount": total}]
        result["dimensions"].append(row)
    return result
