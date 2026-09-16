from datetime import UTC, datetime, timedelta


class Demo:
    """Synthetic, clock-relative fixture. No AWS or email calls."""

    def account_id(self):
        return "123456789012"

    def costs(self, today, account):
        rows = []
        for n in range(35, 0, -1):
            day = today - timedelta(days=n)
            for service, amount in [
                ("Amazon EC2", 120 if n > 3 else 215),
                ("Amazon RDS", 80),
                ("Amazon S3", 18),
                ("Amazon VPC", 32),
            ]:
                rows.append(
                    {
                        "day": str(day),
                        "service": service,
                        "region": "us-east-1",
                        "amount": str(amount),
                        "currency": "USD",
                        "estimated": n < 7,
                    }
                )
        return rows

    def forecast(self, today, account):
        end = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        return {
            "remaining": str((end - today).days * 345),
            "currency": "USD",
            "method": "synthetic demo forecast",
        }

    def allocation_tags(self):
        return {"Project": "Active", "Owner": "Active"}

    def team_costs(self, today, account, tag):
        from decimal import Decimal

        total = sum(
            (
                Decimal(r["amount"])
                for r in self.costs(today, account)
                if r["day"] >= str(today.replace(day=1))
            ),
            Decimal(0),
        )
        names = ["Platform", "Payments", ""] if tag == "Project" else ["Infrastructure", "Product", ""]
        return [
            {"value": name, "amount": str(total * fraction), "currency": "USD"}
            for name, fraction in zip(names, [Decimal("0.5"), Decimal("0.3"), Decimal("0.2")], strict=True)
        ]

    def recommendations(self, account):
        return [
            {
                "id": "demo-rec-ec2",
                "resource_id": "i-demo-staging",
                "region": "us-east-1",
                "action": "Rightsize staging instance after workload review",
                "monthly_savings": "142.30",
                "currency": "USD",
                "effort": "Low",
                "restart_needed": True,
                "source": "Synthetic demonstration; not an AWS recommendation",
            },
            {
                "id": "demo-rec-ebs",
                "action_type": "Delete",
                "resource_type": "EbsVolume",
                "last_refresh": datetime.now(UTC).isoformat(),
                "resource_id": "vol-demo-unattached",
                "region": "us-east-1",
                "action": "Review unattached volume retention before deletion",
                "monthly_savings": "40.00",
                "currency": "USD",
                "effort": "Low",
                "restart_needed": False,
                "source": "Synthetic demonstration; not an AWS recommendation",
            },
        ]

    def enrich_event(self, event):
        event["owner"] = "Payments (demo)"
        event["estimate"] = {
            "monthly": "280.32",
            "assumptions": "Synthetic example, not a current AWS price.",
        }
        return event

    def event(self):
        return {
            "id": "demo-envelope",
            "detail-type": "AWS API Call via CloudTrail",
            "account": self.account_id(),
            "region": "us-east-1",
            "time": datetime.now(UTC).isoformat(),
            "detail": {
                "eventID": "demo-creation-001",
                "eventSource": "ec2.amazonaws.com",
                "eventName": "RunInstances",
                "recipientAccountId": self.account_id(),
                "userIdentity": {"arn": "arn:aws:sts::123456789012:assumed-role/deploy/pipeline"},
                "responseElements": {"instancesSet": {"items": [{"instanceId": "i-demo-staging"}]}},
            },
        }
