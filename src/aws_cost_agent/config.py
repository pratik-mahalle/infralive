import tomllib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path


@dataclass
class Config:
    database: str = "data/agent.sqlite3"
    outbox_dir: str = "data/email-preview"
    demo: bool = False
    profile: str | None = None
    role_arn: str = ""
    external_id: str = ""
    account_id: str = ""
    region: str = "us-east-1"
    queues: dict[str, str] = field(default_factory=dict)
    history_regions: list[str] = field(default_factory=list)
    delivery: str = "preview"
    sender: str = ""
    recipients: list[str] = field(default_factory=list)
    model_id: str = ""
    anomaly_dollars: Decimal = Decimal("25")
    anomaly_percent: Decimal = Decimal("30")
    monthly_budget: Decimal = Decimal("0")
    creation_alerts: bool = True
    routine_creation_alerts: bool = False
    idle_alerts: bool = True
    idle_monthly_savings: Decimal = Decimal("25")
    idle_reminder_days: int = 7
    unused_after_days: int = 7
    sync_hours: int = 6
    digest_hour_utc: int = 8
    project_tag: str = "Project"
    owner_tag: str = "Owner"
    cloud_bucket: str = ""
    cloud_function: str = ""
    cloud_region: str = ""


def load_config(path: str | None, demo: bool = False) -> Config:
    data = {}
    if path:
        with open(path, "rb") as file:
            data = tomllib.load(file)
    aws, agent, mail, ai = (data.get(k, {}) for k in ("aws", "agent", "notifications", "ai"))
    team, cloud = data.get("team", {}), data.get("cloud", {})
    c = Config(
        database=agent.get("database", "data/agent.sqlite3"),
        outbox_dir=mail.get("preview_directory", "data/email-preview"),
        demo=demo,
        profile=aws.get("profile") or None,
        role_arn=aws.get("role_arn", ""),
        external_id=aws.get("external_id", ""),
        account_id=str(aws.get("account_id", "")),
        region=aws.get("region", "us-east-1"),
        queues=aws.get("queues", {}),
        history_regions=aws.get("history_regions", []),
        delivery=mail.get("delivery", "preview"),
        sender=mail.get("sender", ""),
        recipients=mail.get("recipients", []),
        model_id=ai.get("bedrock_model_id", ""),
        anomaly_dollars=Decimal(str(agent.get("anomaly_dollars", 25))),
        anomaly_percent=Decimal(str(agent.get("anomaly_percent", 30))),
        monthly_budget=Decimal(str(agent.get("monthly_budget", 0))),
        creation_alerts=agent.get("creation_alerts", True),
        routine_creation_alerts=agent.get("routine_creation_alerts", False),
        idle_alerts=agent.get("idle_alerts", True),
        idle_monthly_savings=Decimal(str(agent.get("idle_monthly_savings", 25))),
        idle_reminder_days=int(agent.get("idle_reminder_days", 7)),
        unused_after_days=int(agent.get("unused_after_days", 7)),
        sync_hours=int(agent.get("sync_hours", 6)),
        digest_hour_utc=int(agent.get("digest_hour_utc", 8)),
        project_tag=team.get("project_tag", "Project"),
        owner_tag=team.get("owner_tag", "Owner"),
        cloud_bucket=cloud.get("state_bucket", ""),
        cloud_function=cloud.get("function_name", ""),
        cloud_region=cloud.get("region", aws.get("region", "us-east-1")),
    )
    if demo:
        c.database = "data/demo.sqlite3"
        c.outbox_dir = "data/demo-email-preview"
        c.delivery = "preview"
        c.model_id = ""
        c.account_id = "123456789012"
        c.monthly_budget = Decimal("10000")
        c.cloud_bucket = c.cloud_function = ""
    if bool(c.cloud_bucket) != bool(c.cloud_function):
        raise ValueError("Cloud monitoring requires both state_bucket and function_name")
    if any(
        not isinstance(key, str) or not key.strip() or len(key) > 128 for key in (c.project_tag, c.owner_tag)
    ):
        raise ValueError("Team tag keys must be nonempty strings of at most 128 characters")
    if c.delivery not in {"preview", "ses"}:
        raise ValueError("notifications.delivery must be preview or ses")
    if (
        not isinstance(c.history_regions, list)
        or len(c.history_regions) > 10
        or any(not isinstance(r, str) or not r for r in c.history_regions)
    ):
        raise ValueError("aws.history_regions must contain at most ten region names")
    if c.delivery == "ses" and (not c.sender or not c.recipients):
        raise ValueError("SES delivery requires a sender and at least one recipient")
    if not isinstance(c.recipients, list) or len(c.recipients) > 50:
        raise ValueError("recipients must be an array with at most 50 addresses")
    if any("@" not in a or "\n" in a or "\r" in a for a in c.recipients + ([c.sender] if c.sender else [])):
        raise ValueError("Invalid email address")
    if c.role_arn and not c.external_id:
        raise ValueError("Cross-account access requires an external_id")
    if c.account_id and (len(c.account_id) != 12 or not c.account_id.isdigit()):
        raise ValueError("account_id must contain 12 digits")
    if c.sync_hours < 1 or not 0 <= c.digest_hour_utc <= 23:
        raise ValueError("sync_hours must be positive and digest_hour_utc must be 0–23")
    if not 1 <= c.idle_reminder_days <= 365:
        raise ValueError("idle_reminder_days must be between 1 and 365")
    if not 1 <= c.unused_after_days <= 365:
        raise ValueError("unused_after_days must be between 1 and 365")
    if any(
        not v.is_finite() or v < 0
        for v in (c.anomaly_dollars, c.anomaly_percent, c.monthly_budget, c.idle_monthly_savings)
    ):
        raise ValueError("Cost thresholds must be finite, nonnegative numbers")
    Path(c.database).parent.mkdir(parents=True, exist_ok=True)
    return c
