from datetime import date, timedelta
from decimal import Decimal

import pytest

from aws_cost_agent.analysis import analyze

TODAY = date(2026, 9, 16)


def test_spike_excludes_yesterday_and_today(provider, config):
    rows = provider.costs(TODAY, "123456789012")
    rows.append(
        {
            "day": str(TODAY),
            "service": "New service",
            "region": "global",
            "amount": "999999",
            "currency": "USD",
            "estimated": True,
        }
    )
    analysis = analyze(rows, TODAY, config)
    assert analysis["month_to_date"] == "4035.00"
    assert len(analysis["anomalies"]) == 1
    anomaly = analysis["anomalies"][0]
    assert anomaly["day"] == "2026-09-14"
    assert anomaly["increase"] == "95.00"
    assert anomaly["percent"] == "79.17"


def test_missing_baseline_day_is_not_zero(provider, config):
    rows = [r for r in provider.costs(TODAY, "123456789012") if r["day"] != "2026-09-07"]
    analysis = analyze(rows, TODAY, config)
    assert analysis["anomalies"] == []
    assert analysis["anomaly_coverage"] == "insufficient history"


def test_small_dollar_spikes_do_not_page(provider, config):
    config.anomaly_dollars = Decimal("100")
    assert analyze(provider.costs(TODAY, "123456789012"), TODAY, config)["anomalies"] == []


def test_new_service_uses_dollar_threshold(provider, config):
    rows = provider.costs(TODAY, "123456789012")
    rows.append(
        {
            "day": str(TODAY - timedelta(days=2)),
            "service": "New service",
            "region": "global",
            "amount": "50.10",
            "currency": "USD",
        }
    )
    new = next(a for a in analyze(rows, TODAY, config)["anomalies"] if a["service"] == "New service")
    assert new["baseline"] == "0.00"
    assert new["percent"] is None


def test_mixed_currencies_rejected(provider, config):
    rows = provider.costs(TODAY, "123456789012")
    rows[0]["currency"] = "EUR"
    with pytest.raises(ValueError, match="currencies"):
        analyze(rows, TODAY, config)


def test_decimal_arithmetic_and_credits(config):
    rows = [
        {"day": "2026-09-01", "service": "S3", "region": "global", "amount": a, "currency": "USD"}
        for a in ("0.1", "0.2", "-0.05")
    ]
    assert analyze(rows, TODAY, config)["month_to_date"] == "0.25"


def test_first_of_month_has_zero_current_month_spend(provider, config):
    today = date(2026, 10, 1)
    result = analyze(provider.costs(today, "123456789012"), today, config)
    assert result["month_to_date"] == "0.00"
    assert result["top_services"] == []


def test_credits_do_not_hide_real_spend_or_service_breakdown(config):
    rows = [
        {
            "day": "2026-09-01",
            "service": "EC2",
            "region": "us-east-1",
            "amount": "121.2073733771",
            "currency": "USD",
            "record_type": "Charge",
        },
        {
            "day": "2026-09-01",
            "service": "Credit",
            "region": "global",
            "amount": "-121.2073751064",
            "currency": "USD",
            "record_type": "Credit",
        },
    ]
    result = analyze(rows, TODAY, config)
    assert result["spend_before_credits"] == "121.21"
    assert result["credits"] == "-121.21"
    assert result["month_to_date"] == "0.00"
    assert result["top_services"] == [{"service": "EC2", "amount": "121.21"}]


def test_refunds_are_separate_and_non_credit_discounts_remain_in_charges(config):
    rows = [
        {
            "day": "2026-09-01",
            "service": service,
            "region": "global",
            "amount": amount,
            "currency": "USD",
            "record_type": kind,
        }
        for service, amount, kind in (
            ("EC2", "200", "Charge"),
            ("EC2", "-20", "Charge"),
            ("Credit", "-50", "Credit"),
            ("Refund", "-10", "Refund"),
        )
    ]
    result = analyze(rows, TODAY, config)
    assert result["spend_before_credits"] == "180.00"
    assert result["month_to_date"] == "120.00"
    assert result["refunds"] == "-10.00"


def test_spikes_still_detected_when_credits_offset_every_charge(provider, config):
    rows = provider.costs(TODAY, "123456789012")
    credits = [{**r, "record_type": "Credit", "amount": str(-Decimal(r["amount"]))} for r in rows]
    result = analyze(rows + credits, TODAY, config)
    assert result["month_to_date"] == "0.00"
    assert result["spend_before_credits"] == "4035.00"
    assert result["anomalies"][0]["increase"] == "95.00"


def test_credit_only_period_keeps_billing_date_and_negative_net(config):
    rows = [
        {
            "day": "2026-09-15",
            "service": "Credit",
            "region": "global",
            "amount": "-10",
            "currency": "USD",
            "record_type": "Credit",
        }
    ]
    result = analyze(rows, TODAY, config)
    assert result["billing_through"] == "2026-09-15"
    assert result["spend_before_credits"] == "0.00"
    assert result["month_to_date"] == "-10.00"
    assert result["anomaly_coverage"] == "insufficient history"
