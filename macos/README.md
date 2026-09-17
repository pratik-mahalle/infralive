# Cloudwake for macOS

A native SwiftUI menu bar companion for AWS Cost Agent. Supports local or always-on AWS collection. Requires macOS 13 or later and
Xcode Command Line Tools (`xcode-select --install`) to build. No third-party Swift dependencies.

For the standalone download and Homebrew installation, see [Install Cloudwake](../docs/downloads.md).

## Build and open

From the project root, after installing the Python agent:

```sh
bash macos/build.sh
open "dist/Cloudwake.app"
```

Look for the cloud and spending amount in the **macOS menu bar**. There is no Dock icon.
On first launch, the app uses demo data. Click the cloud to see:

- Month-to-date charges before credits/refunds, credits, net balance, forecast and billing freshness.
- A 14-day spending chart, largest services and cost alerts.
- Recorded resource creations with the actual AWS principal and available ownership.
- Savings recommendations with estimates and restart implications.
- A report button, with “Ask about spending…” and email previews in the ellipsis menu.

The compact menu uses native controls and follows the Mac's light or dark appearance. Expand
activity and savings rows for full resource IDs, AWS identities and supporting evidence.
Billing methodology and collection notes are under **Overview → Billing details**.

## Multiple AWS accounts

In Settings, use **Add or reconnect an account** for each AWS account. Give it a name such as
Production or Staging, then check and connect it using its own AWS profile or pasted credentials.
The account picker in the menu and Settings switches the displayed spending, changes, savings,
and inbox. Other accounts keep monitoring, and Mac notification banners identify their account.
There is one saved connection per AWS account; reconnecting selects or updates that connection.
Reconnecting restarts only that account’s local worker so updated credentials take effect.

**Your accounts** shows each connection's monitoring or sign-in state and offers per-account
Start, Pause, Rename, and Remove controls. Removing an account stops its local worker but keeps
its data, credentials, and any deployed AWS monitor. Existing v1 connections migrate automatically.
Selection and local monitoring preferences survive app relaunch. The menu bar amount belongs
to the selected account; it is not a combined organization bill.

Local monitors require the app to be open and the Mac awake. Configure the optional always-on
collector separately for each account to collect while the Mac is asleep. An expired session in
one account keeps its last snapshot visible and does not stop the other accounts.

## Alert inbox

Open **Inbox** to see resource, spending, budget and unused-resource alerts saved for the connected account.
The tab shows the unread count. Opening an alert marks it read; it remains in **Open** until
you mark it reviewed or snooze it. Details preserve the original evidence, including resource,
AWS identity, idle observation period and cost estimate whenever the alert includes them.

- **Mark reviewed** moves an alert to **Reviewed**. **Reopen** returns it to Open as unread.
- **Snooze** offers one hour, one day or one week. The alert moves to **Snoozed**, then returns
  to Open as unread when the time expires. **Unsnooze** returns it immediately.
- **Unread** keeps an alert open and restores its unread indicator. **Copy details** copies
  the title and full evidence. Older alerts are available using **Older** and **Newer**.

Inbox state survives restarts and is scoped to each connection's database. Existing saved
notifications appear automatically; imported CloudTrail history that never generated an alert
stays in Changes. Inbox actions do not change AWS resources, email delivery or desktop notification
cursors. Snoozing affects this inbox entry only; it does not schedule an extra email or Mac banner,
and new alerts for the same resource still arrive normally. Local status refreshes every 30 seconds,
including when monitoring is paused; expired snoozes also return when the app is next opened.
The refresh button in Inbox reads saved state: local SQLite for local connections, or private S3 state for cloud connections. It does not recollect AWS billing data.

The compiled app is at `dist/Cloudwake.app`. This is a **local companion**, not a self-contained
distribution: it runs the project's Python environment. The build embeds this project's path;
if you move the project or app, update Settings. No AWS credentials are embedded in the bundle.

## Connect AWS

Open the gear icon → choose an **AWS profile** and **Resource region** → **Check account** →
confirm the detected account → **Connect this account**. New accounts start local monitoring automatically.
There is no need to type an account ID, edit TOML or copy queue URLs. The app saves each
account/profile/region connection separately under `data/connections/`; its database and email
previews are isolated. Existing settings in a generated connection are preserved on reconnect.

Use **Sign in with SSO…** to renew an existing IAM Identity Center profile in your browser.
If this Mac has no AWS profiles, the screen links to the AWS CLI setup guide. Other credential
types use your existing sign-in method. Apps opened from Finder do not inherit Terminal-only
environment variables.

The checklist shows access to spending data, idle-resource insights, CloudTrail history and
optional event delivery. Missing AWS features have console links. A successful
recommendation check does not mean AWS has already generated findings for all your resources.
**Set up resource notifications…** lets you review and install the regional event stack with
your selected profile; deployment permissions and an existing active trail are required.
The app discovers and saves the queue URL automatically. Existing event stacks are reused.
If installation times out, inspect the linked CloudFormation console and check again; the
stack may still be creating. Nothing is deployed by **Check account** or **Connect this account**.

Expand **Advanced settings & demo** for custom file paths/configuration, cross-account roles,
additional regions, email setup or demo mode. Complete permission and enrollment details are
in the [AWS setup guide](../README.md#connect-an-aws-account).

**Refresh** calls the collector; it can make billable AWS API requests. The app's automatic
30-second refresh only reads local SQLite state via `aws-cost-agent status` and never calls AWS.
AWS billing remains delayed; the menu shows the source billing date and warns on old snapshots.

**Start monitoring** runs the existing agent worker with your configured delivery mode. If the config uses
SES, that worker will send emails to the configured recipients. Demo always uses local previews.
The footer's **Pause** stops only the worker launched by this app. A worker started in Terminal
stays under Terminal control, as noted in the ellipsis menu. An advisory lock prevents duplicate workers.

Monitoring starts only when you press Start. It pauses during Mac sleep and stops when this app
quits. Use a server deployment for continuous monitoring independent of your laptop. A hard kill
of the app can leave its worker running; it will be recognized as an external worker on relaunch.
This version has no login-item installation or automatic cloud remediation.

## Team spending and cloud monitoring

In **Overview**, choose **Project** or **Owner** below the chart. Both are separate views of the
same charges before credits and refunds, using case-sensitive billing tags. Unavailable attribution
shows the known total as Unassigned with an explanation. The tag-management link opens AWS Billing.

For an activated cloud connection, the footer says **Monitoring in AWS** and the collector keeps
running while the Mac sleeps or the app is closed. Inbox actions update the private cloud state.
Settings show cloud health and the Lambda console link. Local Start/Pause controls are replaced
by cloud status; quitting the app does not stop AWS collection. Email remains disabled.
Follow the [always-on guide](../docs/always-on.md) to deploy, pause, or recover the cloud service.

## Mac notifications

Open the gear icon → **Mac notifications → Enable…** → allow notifications in the macOS prompt.
With the worker running, banners report new resource creation calls, spending increases,
budget breaches and fresh AWS idle-resource findings above your configured threshold
(USD 25/month in estimated savings by default). Creation alerts identify the actual AWS
principal, which may be a deployment role rather than a named teammate.

Enabling starts with new alerts; it does not replay the existing backlog. More than three alerts
in one polling batch are grouped into a summary to avoid a burst of banners. The app checks its
local alert feed every 30 seconds while running and awake. Its saved cursor survives relaunches,
and demo and live feeds are isolated. Demo banners are explicitly labeled. Email delivery and
Mac delivery have independent state, so previewing email does not consume desktop alerts.
Permission failures leave alerts available for retry. Use **Pause** to disable desktop delivery;
if macOS blocked permission, change it in System Settings → Notifications → Cloudwake.

AWS collection and CloudTrail delivery have their own delays and coverage limits; see
[resource monitoring](../README.md#monitor-teammate-created-resources) and
[idle-resource monitoring](../README.md#idle-resource-monitoring). Redeploy existing regional
event stacks to enable the expanded creation-event coverage.

## Changes and Savings

**Changes** imports seven days of recent CloudTrail management activity when monitoring starts,
then checks every five minutes. The header's refresh button refreshes history without querying
billing when **Changes** is selected; in other tabs it refreshes costs and activity.
It shows create, update and delete calls; historical imports do not send old notifications.
Routine log streams, network interfaces and target registration are hidden by default;
use **Routine activity** to show them. Their creation alerts
are also off by default; enable `agent.routine_creation_alerts` if needed.
No event queue or active trail is needed for Event History. The connected role needs
`cloudtrail:LookupEvents`. The selected resource region is used unless `aws.history_regions`
lists additional regions. Busy accounts show a backfill-in-progress notice.

**Savings** distinguishes AWS estimates from review priorities based on your actual service
charges. **Enable AWS analysis…** opts in only the currently connected account, after showing
the scope. Every connected account has its own enrollment. Standard analysis is used; paid
enhanced metrics and automatic remediation stay off. AWS needs time to prepare findings.
Review priorities provide useful investigation steps while estimated savings are unavailable.
**Unused resources** shows observation progress and alerts; **What’s monitored** explains coverage.

Cloudwake keeps the original bundle identifier and preference keys so renaming preserves
your connection and notification settings. The custom icon's editable vector master is
`macos/Sources/CostBar/BrandMark.swift`; the build creates all macOS icon sizes and the ICNS bundle.

Settings contain local file paths and mode only. AWS access keys stay in the AWS credential chain.
Worker logs are in `data/menubar-demo.log` or `data/menubar-worker.log`. Full reports are exported
to `data/demo-report.txt` / `data/aws-report.txt`. Quit from the menu's ellipsis button.

## Verification

```sh
bash macos/test.sh
pytest -q
```

The Swift tests use Swift Testing (Swift 6+ toolchain) and validate the Python/Swift JSON contract,
notification grouping and feed isolation, optional fields, timestamps and literal subprocess
argument handling. Python tests cover event coverage, idle thresholds and reminders, durable
notification pagination, the status interface and worker lock. Tests do not send OS banners or email.
To render the menu with the committed synthetic fixture for layout inspection:

```sh
"dist/Cloudwake.app/Contents/MacOS/CostBar" --render /tmp/cost-bar.png \
  macos/Tests/CostBarTests/Fixtures/demo-status.json
```

Add `--dark` for the dark appearance or `--settings` to render the connection screen (local profile
discovery only; no AWS calls). The app is ad-hoc signed for this Mac; distributing it to
other Macs requires Developer ID signing/notarization and a Python runtime installation strategy.

Use `--inbox --inbox-data macos/Tests/CostBarTests/Fixtures/inbox.json` for the synthetic inbox,
and add `--inbox-detail` to render its first alert. Rendering cannot read or mutate the real inbox.
