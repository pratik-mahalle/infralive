"""Evidence-based review leads, deliberately separate from AWS savings estimates."""

from decimal import Decimal

GUIDES = [
    (
        "Elastic Container Service",
        "Review ECS task sizing and schedules",
        "Compare requested CPU/memory with observed utilization. Review minimum task counts and non-production schedules before changing capacity.",
    ),
    (
        "EC2 - Other",
        "Review EBS volumes, snapshots and IP charges",
        "Break this charge into usage types. Check unattached volumes, snapshot retention and unused public IPs; confirm backup and recovery requirements before removal.",
    ),
    (
        "CloudWatch",
        "Review log retention and high-volume metrics",
        "Inspect log groups without retention limits, ingestion volume and custom metrics. Keep the retention and observability your team needs.",
    ),
    (
        "Load Balancing",
        "Review load balancer utilization",
        "Check request volume and target health. Ask the owning team about unused environments before removing any load balancer.",
    ),
    (
        "Virtual Private Cloud",
        "Review NAT and public IP usage",
        "Check NAT traffic paths, idle public IPs and endpoint alternatives. Compare endpoint charges before changing networking.",
    ),
    (
        "Relational Database",
        "Review database sizing and non-production hours",
        "Compare CPU, memory, connections and storage trends. Confirm availability and recovery requirements before resizing or scheduling stops.",
    ),
    (
        "Simple Storage Service",
        "Review object lifecycle and storage classes",
        "Check access patterns, old object versions and incomplete uploads. Account for retrieval charges and minimum storage duration before changing storage classes.",
    ),
    (
        "Compute Cloud",
        "Review EC2 utilization and operating hours",
        "Check CPU and memory over representative workload periods. Review test environments and sizing with the owner; do not stop resources based only on age.",
    ),
]


def review_leads(analysis):
    result = []
    for service in analysis["top_services"]:
        if Decimal(service["amount"]) <= 0:
            continue
        for pattern, title, detail in GUIDES:
            if pattern in service["service"]:
                result.append(
                    {
                        "id": service["service"],
                        "title": title,
                        "detail": detail,
                        "service": service["service"],
                        "period_spend": service["amount"],
                        "currency": analysis["currency"],
                        "source": "Your Cost Explorer charges",
                        "savings_estimate": None,
                    }
                )
                break
    return result[:5]


def recommendation_status(error=None):
    if error is None:
        return {
            "state": "available",
            "message": "AWS recommendations collected. Findings depend on resource coverage and utilization history.",
        }
    response = getattr(error, "response", {}).get("Error", {})
    code = response.get("Code", type(error).__name__)
    message = response.get("Message", "").lower()
    if "not enrolled" in message or "opt in" in message or "opt-in" in message:
        return {
            "state": "not_enrolled",
            "message": "AWS savings recommendations are not enabled for this account. Enable them to receive resource-level estimates.",
        }
    if "AccessDenied" in code:
        return {
            "state": "access_denied",
            "message": "AWS denied access to recommendations. Grant cost-optimization-hub:ListRecommendations to the connected role.",
        }
    return {"state": "unavailable", "message": f"AWS recommendations are temporarily unavailable ({code})."}
