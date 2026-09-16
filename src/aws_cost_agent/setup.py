"""Guided local setup. AWS writes occur only in the explicit install-events command."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path

import boto3
from botocore.config import Config as SDKConfig
from botocore.exceptions import ClientError

STACK = "aws-cost-agent-events"


def profiles():
    session = boto3.Session()
    return {"profiles": sorted(session.available_profiles), "regions": session.get_available_regions("ec2")}


def session_for(profile, region):
    if not profile:
        raise ValueError("Choose an AWS profile first.")
    if region not in boto3.Session().get_available_regions("ec2"):
        raise ValueError("Choose a supported AWS region.")
    return boto3.Session(profile_name=profile, region_name=region)


def client(session, service, region=None):
    return session.client(
        service,
        region_name=region,
        config=SDKConfig(connect_timeout=5, read_timeout=15, retries={"mode": "standard", "max_attempts": 2}),
    )


def identity(session, expected=None):
    value = client(session, "sts").get_caller_identity()
    account = value["Account"]
    if not re.fullmatch(r"\d{12}", account) or (expected and expected != account):
        raise ValueError("The signed-in account changed. Check the account again before connecting.")
    return {"account_id": account, "principal": value["Arn"]}


def problem(error):
    if isinstance(error, ValueError):
        return str(error)
    code = getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)
    if "AccessDenied" in code or "Unauthorized" in code:
        return "Permission needed. Ask your AWS administrator to grant access."
    if "OptIn" in code or "DataUnavailable" in code:
        return "Enable this feature in AWS, then allow time for AWS to prepare the data."
    return f"Could not verify ({code}). Check your AWS session and try again."


def stack_queue(session):
    try:
        stacks = client(session, "cloudformation").describe_stacks(StackName=STACK)["Stacks"]
    except ClientError as error:
        detail = error.response["Error"]
        if detail["Code"] == "ValidationError" and "does not exist" in detail.get("Message", ""):
            return None
        raise
    stack = stacks[0]
    if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}:
        raise ValueError(f"Event setup is {stack['StackStatus']}. Check the stack in CloudFormation.")
    return next((o["OutputValue"] for o in stack.get("Outputs", []) if o["OutputKey"] == "QueueUrl"), None)


def logs_writes(selectors):
    for s in selectors.get("EventSelectors", []):
        if s.get("IncludeManagementEvents") and s.get("ReadWriteType") in {"All", "WriteOnly"}:
            if not s.get("ExcludeManagementEventSources"):
                return True
    # Only claim coverage for unrestricted management writes. Custom filters need review.
    for s in selectors.get("AdvancedEventSelectors", []):
        fields = s.get("FieldSelectors", [])
        category = any(f == {"Field": "eventCategory", "Equals": ["Management"]} for f in fields)
        allowed = all(
            f == {"Field": "eventCategory", "Equals": ["Management"]}
            or f == {"Field": "readOnly", "Equals": ["false"]}
            for f in fields
        )
        if category and allowed:
            return True
    return False


def trail_ready(session, region):
    trails = client(session, "cloudtrail").describe_trails(includeShadowTrails=True)["trailList"]
    for trail in trails:
        if not trail.get("IsMultiRegionTrail") and trail.get("HomeRegion") != region:
            continue
        ct = client(session, "cloudtrail", trail.get("HomeRegion", region))
        if ct.get_trail_status(Name=trail["TrailARN"]).get("IsLogging"):
            if logs_writes(ct.get_event_selectors(TrailName=trail["TrailARN"])):
                return True
    return False


def check(profile, region, session=None):
    session = session or session_for(profile, region)
    result = {**identity(session), "profile": profile, "region": region, "checks": []}

    def probe(key, title, operation, ready, missing):
        try:
            ok = bool(operation())
            result["checks"].append(
                {"id": key, "title": title, "ready": ok, "detail": ready if ok else missing}
            )
        except Exception as error:
            result["checks"].append({"id": key, "title": title, "ready": False, "detail": problem(error)})

    def cost_access():
        today = date.today()
        client(session, "ce", "us-east-1").get_cost_and_usage(
            TimePeriod={"Start": str(today - timedelta(days=2)), "End": str(today - timedelta(days=1))},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
        )
        return True

    def savings_access():
        client(session, "cost-optimization-hub", "us-east-1").list_recommendations(
            filter={"accountIds": [result["account_id"]]}, maxResults=1
        )
        return client(session, "compute-optimizer", region).get_enrollment_status().get("status") == "Active"

    probe("costs", "Spending data", cost_access, "Cost Explorer is accessible.", "Enable Cost Explorer.")
    probe(
        "savings",
        "Idle-resource insights",
        savings_access,
        "Recommendations are accessible. Findings depend on AWS coverage and utilization history.",
        "Enable Cost Optimization Hub and opt in to Compute Optimizer.",
    )
    probe(
        "history",
        "Recent activity access",
        lambda: client(session, "cloudtrail").lookup_events(
            MaxResults=1, LookupAttributes=[{"AttributeKey": "ReadOnly", "AttributeValue": "false"}]
        ),
        "CloudTrail history is accessible. No event queue is needed for history polling.",
        "Grant cloudtrail:LookupEvents to read recent activity.",
    )
    probe(
        "trail",
        "Faster delivery: trail (optional)",
        lambda: trail_ready(session, region),
        "An active trail logs management writes in this region.",
        "Enable an active CloudTrail trail with write management events in this region.",
    )
    probe(
        "events",
        "Faster delivery: queue (optional)",
        lambda: stack_queue(session),
        "Event infrastructure is installed. Queue consumption is checked when monitoring starts.",
        "Optional: install event delivery. History polling works without this queue.",
    )
    return result


def write_connection(profile, region, account, queue=None, root=Path(".")):
    # Separate account/profile/region scopes cannot mix billing evidence or pending alerts.
    key = hashlib.sha256(f"{account}|{profile}|{region}".encode()).hexdigest()[:16]
    folder = (root / "data" / "connections" / key).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "config.toml"
    if target.exists():
        # Preserve user customization. Only this generated queue section is managed here.
        import tomllib

        existing = tomllib.loads(target.read_text())
        aws = existing.get("aws", {})
        if (aws.get("account_id"), aws.get("profile"), aws.get("region")) != (account, profile, region):
            raise ValueError(
                "Saved connection was customized for another account, profile or region. Use Advanced settings."
            )
        content = target.read_text()
        if not queue:
            return str(target)
        marker = "# Cost Bar managed event queue"
        if marker not in content:
            raise ValueError("This configuration was customized. Add the event queue in Advanced settings.")
        before, after = content.split(marker, 1)
        end = after.find("# End managed event queue")
        if end < 0:
            raise ValueError("Managed queue section is incomplete. Check Advanced settings.")
        content = before + queue_section(region, queue) + after[end + len("# End managed event queue") :]
    else:

        def q(value):
            return json.dumps(value, ensure_ascii=False)

        content = (
            f"# Created by Cost Bar. Credentials remain in your AWS profile.\n[aws]\n"
            f"profile = {q(profile)}\nregion = {q(region)}\naccount_id = {q(account)}\n\n"
            f"{queue_section(region, queue)}\n\n[agent]\n"
            f"database = {q(str(folder / 'agent.sqlite3'))}\n"
            "sync_hours = 6\ncreation_alerts = true\nidle_alerts = true\nidle_monthly_savings = 25\nidle_reminder_days = 7\n\n"
            f'[notifications]\ndelivery = "preview"\npreview_directory = {q(str(folder / "email-preview"))}\n'
            'sender = ""\nrecipients = []\n'
        )
    fd, temporary = tempfile.mkstemp(dir=folder, prefix=".config-")
    try:
        with os.fdopen(fd, "w") as file:
            file.write(content)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return str(target)


def queue_section(region, queue):
    return (
        "# Cost Bar managed event queue\n[aws.queues]\n"
        + (f"{json.dumps(region)} = {json.dumps(queue)}\n" if queue else "")
        + "# End managed event queue"
    )


def connect(profile, region, account, session=None, root=Path(".")):
    session = session or session_for(profile, region)
    identity(session, account)
    warning = None
    try:
        queue = stack_queue(session)
    except Exception as error:
        queue = None
        warning = problem(error)
    return {"config_path": write_connection(profile, region, account, queue, root), "warning": warning}


def install_events(profile, region, account, session=None, root=Path(".")):
    session = session or session_for(profile, region)
    identity(session, account)
    if not trail_ready(session, region):
        raise ValueError("Enable a CloudTrail trail with write management events in this region, then retry.")
    cf = client(session, "cloudformation")
    queue = stack_queue(session)
    if not queue:
        template = (root / "infra" / "events.json").read_text()
        cf.create_stack(
            StackName=STACK, TemplateBody=template, Tags=[{"Key": "Application", "Value": "CostBar"}]
        )
        cf.get_waiter("stack_create_complete").wait(
            StackName=STACK, WaiterConfig={"Delay": 5, "MaxAttempts": 120}
        )
        queue = stack_queue(session)
    if not queue:
        raise ValueError("The stack has no QueueUrl output. Check it in CloudFormation.")
    return {"config_path": write_connection(profile, region, account, queue, root), "warning": None}


def execute(args):
    if args.setup_action == "profiles":
        return profiles()
    if args.setup_action == "check":
        return check(args.profile, args.region)
    if args.setup_action == "login":
        executable = shutil.which("aws") or next(
            (p for p in ("/opt/homebrew/bin/aws", "/usr/local/bin/aws") if os.access(p, os.X_OK)), None
        )
        if not executable:
            raise ValueError("Install AWS CLI v2 to sign in with SSO.")
        try:
            result = subprocess.run(
                [executable, "sso", "login", "--profile", args.profile],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=180,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ValueError("Sign-in timed out. Try again and complete the browser sign-in.") from error
        if result.returncode:
            raise ValueError(
                "SSO sign-in failed. This button requires an IAM Identity Center profile. Refresh other credential types using your existing AWS sign-in method."
            )
        return {"signed_in": True}
    if args.setup_action == "connect":
        return connect(args.profile, args.region, args.account)
    return install_events(args.profile, args.region, args.account)
