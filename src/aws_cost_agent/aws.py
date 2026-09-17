"""Read-only customer connectors; email and model calls use the operator identity."""

import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .analysis import money
from .credentials import session_for
from .events import clean


class AWS:
    def __init__(self, config):
        from botocore.config import Config as SDKConfig

        self.config = config
        self.base = session_for(config.profile, config.region)
        self.session = self.base
        self.expires = 0
        self.sdk_config = SDKConfig(
            retries={"mode": "standard", "max_attempts": 5}, connect_timeout=10, read_timeout=30
        )
        self._prices = {}
        self._history_calls = {}

    def client(self, service, region=None, operator=False):
        import boto3

        if not operator and self.config.role_arn and time.time() >= self.expires:
            sts = self.base.client("sts", config=self.sdk_config)
            result = sts.assume_role(
                RoleArn=self.config.role_arn,
                ExternalId=self.config.external_id,
                RoleSessionName="aws-cost-agent",
                DurationSeconds=3600,
            )
            c = result["Credentials"]
            self.session = boto3.Session(
                aws_access_key_id=c["AccessKeyId"],
                aws_secret_access_key=c["SecretAccessKey"],
                aws_session_token=c["SessionToken"],
            )
            self.expires = c["Expiration"].timestamp() - 300
        session = self.base if operator else self.session
        return session.client(service, region_name=region or self.config.region, config=self.sdk_config)

    def account_id(self):
        actual = self.client("sts").get_caller_identity()["Account"]
        if self.config.account_id and actual != self.config.account_id:
            raise ValueError("AWS credentials do not match configured account_id")
        return actual

    @staticmethod
    def cost_filter(account, adjustments=False):
        adjustment_types = {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit", "Refund"]}}
        return {
            "And": [
                {"Dimensions": {"Key": "LINKED_ACCOUNT", "Values": [account]}},
                adjustment_types if adjustments else {"Not": adjustment_types},
            ]
        }

    def unattached_volumes(self, region):
        """Complete regional inventory; propagate pagination errors rather than partial success."""
        result = []
        pages = (
            self.client("ec2", region)
            .get_paginator("describe_volumes")
            .paginate(Filters=[{"Name": "status", "Values": ["available"]}])
        )
        for page in pages:
            for volume in page.get("Volumes", []):
                if volume.get("State") != "available" or volume.get("Attachments"):
                    continue
                result.append(
                    {
                        "resource_id": volume["VolumeId"],
                        "region": region,
                        "resource_type": "EBS volume",
                        "source": "EC2 DescribeVolumes",
                        "signal": "Unattached at every successful check",
                        "created_at": volume["CreateTime"].isoformat(),
                        "size_gib": volume.get("Size"),
                    }
                )
        return result

    def costs(self, today, account):
        # Keep charges and credits separate so credits cannot hide infrastructure burn.
        # Cost Explorer supports only two grouping dimensions, requiring two paginated queries.
        start = min(today.replace(day=1), today - timedelta(days=35))
        rows = []
        client = self.client("ce", "us-east-1")
        for adjustments in (False, True):
            args = {
                "TimePeriod": {"Start": str(start), "End": str(today)},
                "Granularity": "DAILY",
                "Metrics": ["UnblendedCost"],
                "Filter": self.cost_filter(account, adjustments),
                "GroupBy": (
                    [{"Type": "DIMENSION", "Key": "RECORD_TYPE"}]
                    if adjustments
                    else [{"Type": "DIMENSION", "Key": "SERVICE"}, {"Type": "DIMENSION", "Key": "REGION"}]
                ),
            }
            while True:
                result = client.get_cost_and_usage(**args)
                for day in result.get("ResultsByTime", []):
                    for group in day.get("Groups", []):
                        amount = group["Metrics"]["UnblendedCost"]
                        rows.append(
                            {
                                "day": day["TimePeriod"]["Start"],
                                "service": group["Keys"][0],
                                "region": "global" if adjustments else (group["Keys"][1] or "global"),
                                "record_type": group["Keys"][0] if adjustments else "Charge",
                                "amount": amount["Amount"],
                                "currency": amount["Unit"],
                                "estimated": day.get("Estimated", True),
                            }
                        )
                if not result.get("NextPageToken"):
                    break
                args["NextPageToken"] = result["NextPageToken"]
        return rows

    def forecast(self, today, account):
        next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        result = self.client("ce", "us-east-1").get_cost_forecast(
            TimePeriod={"Start": str(today), "End": str(next_month)},
            Metric="UNBLENDED_COST",
            Granularity="MONTHLY",
            PredictionIntervalLevel=80,
            Filter=self.cost_filter(account),
        )
        return {
            "remaining": result["Total"]["Amount"],
            "currency": result["Total"]["Unit"],
            "method": "AWS Cost Explorer forecast + month-to-date charges, before credits and refunds",
            "basis": "before_credits_and_refunds",
        }

    def allocation_tags(self):
        client = self.client("ce", "us-east-1")
        tags, args = {}, {"MaxResults": 100}
        while True:
            response = client.list_cost_allocation_tags(**args)
            tags.update({r["TagKey"]: r["Status"] for r in response.get("CostAllocationTags", [])})
            if not response.get("NextToken"):
                return tags
            args["NextToken"] = response["NextToken"]

    def team_costs(self, today, account, tag):
        if today.day == 1:
            return []
        args = {
            "TimePeriod": {"Start": str(today.replace(day=1)), "End": str(today)},
            "Granularity": "MONTHLY",
            "Metrics": ["UnblendedCost"],
            "Filter": self.cost_filter(account),
            "GroupBy": [{"Type": "TAG", "Key": tag}],
        }
        rows = []
        client = self.client("ce", "us-east-1")
        while True:
            response = client.get_cost_and_usage(**args)
            for period in response.get("ResultsByTime", []):
                for group in period.get("Groups", []):
                    key = group["Keys"][0]
                    if not key.startswith(tag + "$"):
                        raise ValueError("AWS returned an unexpected tag grouping")
                    metric = group["Metrics"]["UnblendedCost"]
                    rows.append(
                        {"value": key[len(tag) + 1 :], "amount": metric["Amount"], "currency": metric["Unit"]}
                    )
            if not response.get("NextPageToken"):
                return rows
            args["NextPageToken"] = response["NextPageToken"]

    def recommendations(self, account):
        client = self.client("cost-optimization-hub", "us-east-1")
        args = {"filter": {"accountIds": [account]}, "includeAllRecommendations": False, "maxResults": 100}
        items = []
        while True:
            result = client.list_recommendations(**args)
            for r in result.get("items", []):
                items.append(
                    {
                        "id": r["recommendationId"],
                        "resource_id": r.get("resourceArn") or r.get("resourceId", "Unknown"),
                        "region": r.get("region", "global"),
                        "action": r.get("actionType", "Review"),
                        "action_type": r.get("actionType", "Review"),
                        "resource_type": r.get("currentResourceType", "AWS resource"),
                        "monthly_savings": money(str(r.get("estimatedMonthlySavings", 0))),
                        "currency": r.get("currencyCode", "USD"),
                        "effort": r.get("implementationEffort", "Unknown"),
                        "restart_needed": r.get("restartNeeded", "Unknown"),
                        "source": r.get("source", "Cost Optimization Hub"),
                        "last_refresh": str(r.get("lastRefreshTimestamp", "Unknown")),
                    }
                )
            if not result.get("nextToken"):
                return sorted(items, key=lambda x: Decimal(x["monthly_savings"]), reverse=True)
            args["nextToken"] = result["nextToken"]

    def ec2_hourly_rate(self, region, instance_type):
        key = (region, instance_type)
        if key in self._prices:
            return self._prices[key]
        filters = {
            "regionCode": region,
            "instanceType": instance_type,
            "operatingSystem": "Linux",
            "tenancy": "Shared",
            "preInstalledSw": "NA",
            "capacitystatus": "Used",
            "productFamily": "Compute Instance",
        }
        args = {
            "ServiceCode": "AmazonEC2",
            "Filters": [{"Type": "TERM_MATCH", "Field": k, "Value": v} for k, v in filters.items()],
            "MaxResults": 100,
        }
        prices = set()
        client = self.client("pricing", "us-east-1")
        while True:
            result = client.get_products(**args)
            for raw in result.get("PriceList", []):
                for term in json.loads(raw).get("terms", {}).get("OnDemand", {}).values():
                    for dimension in term.get("priceDimensions", {}).values():
                        if dimension.get("unit") == "Hrs" and dimension.get("beginRange") == "0":
                            rate = Decimal(dimension.get("pricePerUnit", {}).get("USD", "0"))
                            if rate > 0:
                                prices.add(rate)
            if not result.get("NextToken"):
                break
            args["NextToken"] = result["NextToken"]
        # Ambiguous/absent price is unknown; never guess the cheapest SKU.
        price = next(iter(prices)) if len(prices) == 1 else None
        self._prices[key] = price
        return price

    def enrich_event(self, event):
        if event["action"] != "RunInstances" or event["resource_ids"] == ["ID unavailable"]:
            return event
        result = self.client("ec2", event["region"]).describe_instances(InstanceIds=event["resource_ids"])
        instances = [i for r in result["Reservations"] for i in r["Instances"]]
        if not instances:
            return event
        owners, prices = set(), []
        all_priced = len(instances) == len(event["resource_ids"])
        for i in instances:
            tags = {t["Key"].lower(): clean(t["Value"]) for t in i.get("Tags", [])}
            owners.add(tags.get("team") or tags.get("owner") or "Unassigned")
            # Linux/UNIX is distinct from RHEL/SUSE/Windows; unsupported rates stay unknown.
            eligible = (
                i.get("PlatformDetails") == "Linux/UNIX"
                and i.get("Placement", {}).get("Tenancy", "default") == "default"
                and not i.get("InstanceLifecycle")
            )
            rate = self.ec2_hourly_rate(event["region"], i["InstanceType"]) if eligible else None
            if rate is None:
                all_priced = False
            else:
                prices.append(rate)
        event["owner"] = ", ".join(sorted(owners))
        if all_priced:
            event["estimate"] = {
                "monthly": money(sum(prices, Decimal(0)) * 730),
                "assumptions": "AWS public Linux shared-tenancy On-Demand compute rate × 730 hours. "
                "Excludes EBS, network, taxes, CPU credits and discounts. Not a bill or savings forecast.",
            }
        return event

    def receive(self, region, queue):
        client = self.client("sqs", region)
        return client.receive_message(
            QueueUrl=queue, MaxNumberOfMessages=10, WaitTimeSeconds=10, VisibilityTimeout=180
        ).get("Messages", [])

    def history_page(self, region, start, end, token=None):
        previous = self._history_calls.get(region, 0)
        time.sleep(max(0, 0.55 - (time.monotonic() - previous)))
        args = {
            "LookupAttributes": [{"AttributeKey": "ReadOnly", "AttributeValue": "false"}],
            "StartTime": datetime.fromisoformat(start),
            "EndTime": datetime.fromisoformat(end),
            "MaxResults": 50,
        }
        if token:
            args["NextToken"] = token
        self._history_calls[region] = time.monotonic()
        return self.client("cloudtrail", region).lookup_events(**args)

    def enable_recommendations(self):
        # Account-only, standard recommendations. No paid enhanced metrics or automation.
        account = self.account_id()
        results = []
        for service, arguments in (
            ("compute-optimizer", {"status": "Active", "includeMemberAccounts": False}),
            ("cost-optimization-hub", {"status": "Active", "includeMemberAccounts": False}),
        ):
            try:
                self.client(service, "us-east-1").update_enrollment_status(**arguments)
                results.append(
                    {
                        "service": service,
                        "enabled": True,
                        "message": "Enrollment requested. AWS needs time to analyze your resources.",
                    }
                )
            except Exception as error:
                code = getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)
                results.append(
                    {
                        "service": service,
                        "enabled": False,
                        "message": f"Could not enable ({code}). Ask your account administrator to enable this feature.",
                    }
                )
        return {"account_id": account, "results": results}

    def acknowledge(self, region, queue, receipt):
        self.client("sqs", region).delete_message(QueueUrl=queue, ReceiptHandle=receipt)

    def send_email(self, message, config):
        result = self.client("sesv2", operator=True).send_email(
            FromEmailAddress=config.sender,
            Destination={"ToAddresses": config.recipients},
            Content={
                "Simple": {
                    "Subject": {"Data": message["subject"], "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": message["body"], "Charset": "UTF-8"}},
                }
            },
        )
        return result["MessageId"]


def utc_today():
    return datetime.now(UTC).date()
