# Always-on AWS monitoring

Cloudwake can run its collector in AWS instead of relying on an awake Mac. The menu bar app
reads the private cloud database and writes inbox actions through an IAM-authenticated Lambda
invocation. No public endpoint, static API token, access key, SES sender or email recipient is
created. Email is disabled in this deployment.

The service contains:

- A Lambda function (`cloudpulse-monitor`, Python 3.12, 512 MB, four-minute maximum execution).
- An EventBridge rule running every five minutes. Cost collection remains every six hours.
- A private, encrypted, versioned S3 bucket for code, configuration and database snapshots.
- A DynamoDB conditional lease that serializes writers, including inbox actions. The lease
  lasts longer than the invoking Lambda's remaining execution time; expired leases recover
  after crashes. No reserved Lambda concurrency is required.
- A 14-day log group, a dead-letter queue and CloudWatch alarms for failures. Alarm emails
  are not configured.

Lambda, S3, DynamoDB, logs and AWS billing API usage are metered. There is no continuously
running VM or NAT gateway. Actual cost depends on API pagination, account activity and state
size. Old database object versions expire after seven days; the current database is retained.
The storage stack retains its bucket on deletion to preserve history and inbox state.

## Install

Use a direct AWS profile in the monitored account. The deployment profile must be able to
manage these CloudFormation resources, including their IAM role. The collector's runtime
role has infrastructure observation permissions and access to its own state only; it cannot
stop or delete monitored infrastructure or send email. The observer template includes cloud
state reads and invocation access for client roles; existing observer roles may need updating.

```sh
.venv/bin/python scripts/package_cloud.py
.venv/bin/python scripts/deploy_cloud.py --config path/to/config.toml provision
```

Provisioning creates `cloudpulse-storage` and `cloudpulse-monitor` with the schedule disabled,
uploads a code-only bundle with SDK dependencies, removes local credentials from the cloud
configuration, and checks the function's execution identity. It refuses to replace unrelated
stacks and does not overwrite an existing active cloud connection.

Stop the Mac worker, then activate:

```sh
.venv/bin/python scripts/deploy_cloud.py --config path/to/config.toml activate
```

Activation takes a consistent SQLite backup under the worker lock, preserves the notification
feed identity and inbox state, runs the first cloud check, enables the schedule, and atomically
adds `[cloud]` to the local config. The previous file is retained as `config.before-cloud.toml`.
An existing seeded cloud database is preserved during a retry. Never manually overwrite a
running cloud database with an older local copy.

Reopen Cloudwake. Its footer should say **Monitoring in AWS**. Local worker commands are
rejected for a cloud connection, preventing duplicate collectors. The menu polls private S3
state every 30 seconds. Refresh can invoke a cloud check; an inbox mutation may ask you to
retry briefly if the collector currently owns the writer lease. An absent heartbeat after
15 minutes, or a saved collection failure, appears as a warning.

Monitoring continues when the Mac sleeps or the app quits. Mac banners still require the Mac
and app to be running. Alerts collected while away remain in the cloud inbox. Resource history,
cost reporting, and unused-resource tracking retain their existing coverage and data delays.

## Pause and recovery

```sh
.venv/bin/python scripts/deploy_cloud.py --config path/to/config.toml pause
```

This disables the EventBridge schedule through CloudFormation. It does not start a Mac worker.
Inspect the function logs, alarms and dead-letter queue if checks fail. To resume, update the
`ScheduleState` parameter of the `cloudpulse-monitor` stack to `ENABLED` in CloudFormation.
To move back to local monitoring, first disable the cloud schedule and preserve the latest cloud
database, then reconnect the local config. Do not restore a stale database while the cloud writer
is running. Runtime configuration and code upgrades should be performed with the schedule paused;
retain the remote database and its feed identity.
