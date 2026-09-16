<p align="center">
  <img src="docs/assets/cloudwake.svg" width="112" height="112" alt="Cloudwake logo">
</p>
<h1 align="center">Cloudwake</h1>
<p align="center"><strong>Know what your AWS is costing. Catch what it leaves running.</strong></p>
<p align="center">A native Mac menu bar app for AWS spending, resource activity, and savings—with optional monitoring that stays awake in AWS.</p>
<p align="center">
  <a href="https://github.com/pratik-mahalle/infralive/actions/workflows/check.yml"><img src="https://github.com/pratik-mahalle/infralive/actions/workflows/check.yml/badge.svg" alt="Build and tests"></a>
  <img src="https://img.shields.io/badge/macOS-13%2B-0f1d28" alt="macOS 13 or later">
  <img src="https://img.shields.io/badge/Python-3.11%2B-0f1d28" alt="Python 3.11 or later">
  <img src="https://img.shields.io/badge/AWS-only-71efc5" alt="AWS only">
</p>
<p align="center">
  <a href="#try-cloudwake">Quick start</a> ·
  <a href="#connect-your-aws-account">Connect AWS</a> ·
  <a href="docs/always-on.md">Always-on setup</a> ·
  <a href="docs/reference.md">Full reference</a>
</p>

<p align="center">
  <img src="docs/assets/overview.png" width="400" alt="Cloudwake light appearance showing demo spending, forecast, daily costs, and service breakdown">
  <img src="docs/assets/teams-dark.png" width="400" alt="Cloudwake dark appearance showing demo spending grouped by project, including Unassigned">
</p>
<p align="center"><sub>Native SwiftUI. Light and dark appearances. Screenshots use synthetic demo data.</sub></p>

## A clearer view of your cloud

Cloudwake puts the answers a CTO needs one click away: where money is going, what changed,
who created a resource, and what deserves a closer look. Your infrastructure stays under your
control; Cloudwake does not stop, resize, or delete monitored resources.

| View | What you get |
| --- | --- |
| **Overview** | Month-to-date charges, credits and net balance, a monthly forecast, daily spending, and cost increase alerts. |
| **Team spending** | The same bill grouped by `Project` or `Owner`, with an explicit **Unassigned** category. |
| **Changes** | Resource creation, update, and deletion activity from CloudTrail, with the AWS identity behind each event. |
| **Savings** | AWS recommendations with estimated savings, investigation priorities, and repeated unused-resource observations. |
| **Inbox** | Persistent alerts you can review, reopen, and snooze. Optional native Mac notification banners. |
| **Always-on monitoring** | A private collector in your AWS account that keeps checking while your Mac sleeps or the app is closed. |

**Current scope:** a single-account MVP, AWS only. The Python collector can run locally or in
AWS; the desktop app requires macOS. GCP, Azure, organization-wide reporting, and weekly email
are not implemented. The optional local SES integration supports daily reports and alerts;
the always-on deployment keeps email disabled.

## Try Cloudwake

You need **Python 3.11+**. Building the Mac app also needs **macOS 13+** and Xcode Command Line
Tools (`xcode-select --install`). There are no third-party Swift dependencies.

```sh
git clone https://github.com/pratik-mahalle/infralive.git
cd infralive
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock -e .

# Explore with synthetic data. No AWS account or network calls required.
aws-cost-agent demo

# Build and open the menu bar app.
bash macos/build.sh
open dist/Cloudwake.app
```

On first launch, Cloudwake starts in demo mode. Look for its cloud symbol and spending amount
in the menu bar. The local build uses this checkout's Python environment, so keep the project
and `.venv` available. It is not yet a standalone, notarized download.

Prefer a terminal? The CLI works without the Mac app:

```sh
aws-cost-agent --demo report
aws-cost-agent --demo ask "Where can we reduce spending?"
aws-cost-agent --demo inbox list --filter open
```

The Python package and CLI retain the name `aws-cost-agent` for compatibility.

## Connect your AWS account

1. Configure an AWS CLI profile using your existing SSO or credential setup.
2. Open Cloudwake's **Settings** and choose the profile and resource region.
3. Select **Check account**, then **Connect this account**.
4. Enable Mac notifications if you want banners. Use **Savings → Enable AWS savings…** to
   enroll the account in standard AWS recommendation analysis when needed.

The connection check verifies the account and available access. Credentials stay in the AWS
SDK credential chain; they are not copied into the app. Connecting does not deploy cloud
infrastructure. Read calls, including Cost Explorer queries, can incur AWS charges.

For manual configuration, copy [config.example.toml](config.example.toml) to `config.toml`,
set the account and profile, then run:

```sh
aws-cost-agent --config config.toml sync
aws-cost-agent --config config.toml history
aws-cost-agent --config config.toml run
```

See the [connection and IAM reference](docs/reference.md#connect-an-aws-account) for permissions,
cross-account roles, and optional event queues. Billing covers the connected account across
regions; resource activity covers the configured history regions.

### Assign spending to teams

Apply the case-sensitive tags `Project` and `Owner` to resources and activate them as cost-allocation
tags in AWS Billing. Cloudwake then offers both breakdowns in Overview. Missing tag values appear
as **Unassigned**. If a tag is inactive or unavailable, the full known bill stays visible as
Unassigned with a warning. Attribution depends on AWS billing ingestion and may not cover prior
charges. The keys are configurable in `[team]`.

### Keep monitoring while your Mac sleeps

The optional [always-on deployment](docs/always-on.md) runs inside your AWS account:

- CloudTrail activity checks every **5 minutes** and cost collection every **6 hours** by default.
- Lambda execution, private encrypted S3 state, and a DynamoDB lease to serialize state writes.
- A shared inbox, failure logs, a dead-letter queue, and CloudWatch alarms.
- IAM-authenticated access; no public API endpoint or static application token.

The deployment guide covers provisioning, verified handoff from the local worker, and recovery.
AWS service and API usage are metered. Mac banners require an awake Mac and a running app;
alerts collected while you are away remain in the inbox.

## How it works

```mermaid
flowchart LR
    CE[Cost Explorer] --> Collector[Collector]
    COH[Cost Optimization Hub] --> Collector
    CT[CloudTrail history] --> Collector
    EBS[EBS observations] --> Collector
    Schedule[Local worker or EventBridge + Lambda] --> Collector
    Collector --> State[(SQLite evidence and inbox)]
    State --> App[Mac menu bar]
    State --> CLI[CLI reports and investigation]
    State -. Cloud mode .-> S3[Private S3 snapshots]
```

The app reads saved evidence. An optional Bedrock investigator can answer questions using
read-only evidence tools; without it, `ask` routes questions to saved reports. No LLM is required
for cost collection, resource monitoring, or alerts.

## Understand the numbers

- **Spend is before credits and refunds.** A $120 charge offset by $120 of credits appears as
  $120 spend and $0 net. Other applicable discounts remain part of AWS `UnblendedCost`.
- **Billing is delayed.** The reporting period runs from the start of the UTC month through
  yesterday. AWS can revise estimates; this is not a live meter or a final invoice.
- **Savings are estimates.** Recommendations depend on AWS enrollment and supported resources.
  Investigation priorities are not claimed savings.
- **Unused means observed unused.** Duration tracking covers unattached EBS volumes and eligible
  AWS Stop/Delete recommendations. Resource age alone is not evidence of inactivity.
- **Identities are AWS principals.** A deployment role is shown as a role, not guessed to be a
  teammate. CloudTrail coverage is regional and does not guarantee every resource change.

See the [operation reference](docs/reference.md) for exact thresholds, event coverage, retry
behavior, notification delivery, and known limitations.

## Development

```sh
source .venv/bin/activate
ruff check src scripts tests
ruff format --check src scripts tests
pytest -q
bash macos/test.sh
bash macos/build.sh
```

Python tests use fixtures and stubs; the Swift tests use synthetic fixtures. CI runs Python
checks on Linux and builds and tests the native app on macOS. Tests do not send email or require
an AWS account. To validate infrastructure templates, install `pip install -e '.[infra]'` and run
`cfn-lint infra/observer-role.json infra/events.json infra/cloud-storage.json infra/cloud-monitor.json`.

```text
src/aws_cost_agent/   Collection, analysis, notifications, cloud runtime, and CLI
macos/               SwiftUI app, shared vector artwork, and native tests
infra/               CloudFormation templates and IAM examples
scripts/             Cloud packaging and deployment helpers
tests/               Python tests
docs/                Operation guides, branding, and demo screenshots
```

Local configurations, credentials, billing databases, email previews, and build artifacts are
excluded from version control. Use synthetic examples when reporting issues, and redact account
identifiers and resource details from logs or screenshots.

[Mac app guide](macos/README.md) · [Always-on guide](docs/always-on.md) ·
[Operation reference](docs/reference.md) · [Logo and brand assets](docs/brand.md)
