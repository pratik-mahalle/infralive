"""Provision a private monitor, then activate it after stopping the local worker.

No credentials are uploaded. Activation never sends email or modifies monitored resources.
"""

import argparse
import hashlib
import json
import sqlite3
import tempfile
from dataclasses import asdict, replace
from pathlib import Path

from botocore.config import Config as SDKConfig
from botocore.exceptions import ClientError

from aws_cost_agent.cloud_client import invoke
from aws_cost_agent.cloud_runtime import CONFIG_KEY, STATE_KEY
from aws_cost_agent.config import load_config
from aws_cost_agent.locking import worker_lock

ROOT = Path(__file__).resolve().parents[1]


def stack_apply(cf, name, template, parameters=None):
    params = [{"ParameterKey": k, "ParameterValue": str(v)} for k, v in (parameters or {}).items()]
    args = dict(
        StackName=name,
        TemplateBody=template.read_text(),
        Parameters=params,
        Capabilities=["CAPABILITY_IAM"],
        Tags=[{"Key": "Application", "Value": "CloudPulse"}, {"Key": "Project", "Value": "CloudPulse"}],
    )
    try:
        existing = cf.describe_stacks(StackName=name)["Stacks"][0]
    except ClientError as error:
        if (
            error.response["Error"]["Code"] != "ValidationError"
            or "does not exist" not in error.response["Error"]["Message"]
        ):
            raise
        existing = None
    if existing:
        if not any(
            t["Key"] == "Application" and t["Value"] == "CloudPulse" for t in existing.get("Tags", [])
        ):
            raise ValueError(f"{name} is not a CloudPulse-managed stack; refusing to replace it")
        try:
            cf.update_stack(**args)
        except ClientError as error:
            if "No updates are to be performed" not in error.response["Error"].get("Message", ""):
                raise
        else:
            cf.get_waiter("stack_update_complete").wait(
                StackName=name, WaiterConfig={"Delay": 5, "MaxAttempts": 120}
            )
    else:
        cf.create_stack(**args)
        cf.get_waiter("stack_create_complete").wait(
            StackName=name, WaiterConfig={"Delay": 5, "MaxAttempts": 120}
        )
    return {
        o["OutputKey"]: o["OutputValue"]
        for o in cf.describe_stacks(StackName=name)["Stacks"][0].get("Outputs", [])
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("action", choices=["provision", "activate", "pause"])
    args = p.parse_args()
    config = load_config(args.config)
    if config.demo or config.role_arn:
        raise ValueError(
            "Deploy using a direct AWS profile in the monitored account, not demo or an observer role"
        )
    from aws_cost_agent.credentials import session_for

    session = session_for(config.profile, config.region)
    sdk = SDKConfig(retries={"mode": "standard", "max_attempts": 3}, connect_timeout=10, read_timeout=30)
    account = session.client("sts", config=sdk).get_caller_identity()["Account"]
    if account != config.account_id:
        raise ValueError("Deployment profile does not match the connected account")
    cf = session.client("cloudformation", config=sdk)
    s3 = session.client("s3", config=sdk)
    package = ROOT / "dist/cloudpulse-monitor.zip"
    if args.action == "provision":
        if config.cloud_bucket:
            raise ValueError(
                "Already connected to a cloud monitor; use an explicit upgrade procedure to preserve its schedule and state"
            )
        print("Creating private storage…", flush=True)
        outputs = stack_apply(cf, "cloudpulse-storage", ROOT / "infra/cloud-storage.json")
        bucket = outputs["StateBucket"]
        code = package.read_bytes()
        code_key = "packages/" + hashlib.sha256(code).hexdigest() + ".zip"
        s3.put_object(
            Bucket=bucket, Key=code_key, Body=code, ExpectedBucketOwner=account, ServerSideEncryption="AES256"
        )
        cloud = asdict(config)
        cloud.update(
            profile=None,
            role_arn="",
            external_id="",
            model_id="",
            delivery="preview",
            sender="",
            recipients=[],
            cloud_bucket="",
            cloud_function="",
        )
        s3.put_object(
            Bucket=bucket,
            Key=CONFIG_KEY,
            Body=json.dumps(cloud, default=str).encode(),
            ExpectedBucketOwner=account,
            ServerSideEncryption="AES256",
            ContentType="application/json",
        )
        print("Creating the monitor with its schedule disabled…", flush=True)
        outputs = stack_apply(
            cf,
            "cloudpulse-monitor",
            ROOT / "infra/cloud-monitor.json",
            {"StateBucket": bucket, "CodeKey": code_key, "ScheduleState": "DISABLED"},
        )
        probe = replace(
            config, cloud_bucket=bucket, cloud_function=outputs["FunctionName"], cloud_region=config.region
        )
        print(
            json.dumps(
                {
                    "outputs": outputs,
                    "health": invoke(probe, {"action": "health"}),
                    "next": "Stop the local worker, then run activate.",
                }
            ),
            flush=True,
        )
        return
    stack = cf.describe_stacks(StackName="cloudpulse-monitor")["Stacks"][0]
    if not any(t["Key"] == "Application" and t["Value"] == "CloudPulse" for t in stack.get("Tags", [])):
        raise ValueError("Refusing to modify a stack not managed by CloudPulse")
    params = {p["ParameterKey"]: p["ParameterValue"] for p in stack["Parameters"]}
    if args.action == "pause":
        params["ScheduleState"] = "DISABLED"
        stack_apply(cf, "cloudpulse-monitor", ROOT / "infra/cloud-monitor.json", params)
        print("Cloud schedule paused. Local monitoring is not automatically started.")
        return
    bucket = params["StateBucket"]
    remote = replace(
        config, cloud_bucket=bucket, cloud_function="cloudpulse-monitor", cloud_region=config.region
    )
    if config.cloud_bucket:
        raise ValueError("This connection is already using cloud monitoring; refusing to reseed its state")
    # Hold the local lock throughout handoff so a new local worker cannot start mid-copy.
    with worker_lock(config.database):
        try:
            s3.head_object(Bucket=bucket, Key=STATE_KEY, ExpectedBucketOwner=account)
            # Resume a previous failed activation without discarding its state.
            print("Keeping previously seeded cloud state.", flush=True)
        except ClientError as error:
            if error.response["Error"]["Code"] not in {"404", "NoSuchKey", "NotFound"}:
                raise
            with tempfile.TemporaryDirectory() as temporary:
                backup = Path(temporary) / "agent.sqlite3"
                with (
                    sqlite3.connect(f"file:{Path(config.database).resolve()}?mode=ro", uri=True) as source,
                    sqlite3.connect(backup) as target,
                ):
                    source.backup(target)
                s3.put_object(
                    Bucket=bucket,
                    Key=STATE_KEY,
                    Body=backup.read_bytes(),
                    ExpectedBucketOwner=account,
                    ServerSideEncryption="AES256",
                    ContentType="application/vnd.sqlite3",
                )
        print("Running the first cloud check…", flush=True)
        print(json.dumps(invoke(remote, {"action": "tick", "force": True})), flush=True)
        params["ScheduleState"] = "ENABLED"
        stack_apply(cf, "cloudpulse-monitor", ROOT / "infra/cloud-monitor.json", params)
        path = Path(args.config)
        original = path.read_text()
        if "[cloud]" in original:
            raise ValueError("A cloud section already exists; refusing to overwrite it")
        path.with_suffix(".before-cloud.toml").write_text(original)
        contents = (
            original
            + "\n[cloud]\nstate_bucket="
            + json.dumps(bucket)
            + '\nfunction_name="cloudpulse-monitor"\nregion='
            + json.dumps(config.region)
            + "\n"
        )
        temporary = path.with_suffix(".cloud.tmp")
        temporary.write_text(contents)
        temporary.replace(path)
        print(
            json.dumps(
                {
                    "cloud_monitoring": "active",
                    "region": config.region,
                    "state_bucket": bucket,
                    "email": "disabled",
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
