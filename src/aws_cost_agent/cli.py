import argparse
import json
import logging
import sys
from pathlib import Path

from .agent import ask
from .analysis import render_report
from .aws import AWS
from .config import load_config
from .demo import Demo
from .history import collect_history
from .inbox import inbox_page, update_inbox
from .locking import worker_lock
from .notifications import deliver
from .status import status_payload
from .store import Store
from .worker import digest, ingest, run, sync


def parser():
    p = argparse.ArgumentParser(description="AWS cost investigator and notification worker")
    p.add_argument("--config", help="TOML configuration file; AWS credentials use the standard SDK chain")
    p.add_argument("--demo", action="store_true", help="Use isolated synthetic data; never contact AWS")
    commands = p.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup", help="Guided AWS profile connection for the macOS app")
    actions = setup.add_subparsers(dest="setup_action", required=True)
    actions.add_parser("profiles", help="List local AWS profile names without making AWS calls")
    credentials = actions.add_parser(
        "import-credentials", help="Verify credentials from stdin and save in macOS Keychain"
    )
    credentials.add_argument("--region", required=True)
    for action in ("check", "connect", "install-events", "login"):
        command = actions.add_parser(action)
        command.add_argument("--profile", required=True)
        command.add_argument("--region", required=True)
        if action in {"connect", "install-events"}:
            command.add_argument("--account", required=True)
    commands.add_parser("demo", help="Generate synthetic report, change alert and email previews")
    commands.add_parser("login", help="Sign in again using the connected AWS SSO profile")
    commands.add_parser("sync", help="Fetch costs, forecasts and savings; queue threshold alerts")
    commands.add_parser(
        "history", help="Import/poll recent CloudTrail changes without deploying infrastructure"
    )
    commands.add_parser(
        "enable-savings", help="Enable account-only AWS recommendations using standard analysis"
    )
    report = commands.add_parser("report", help="Read the last saved report from local or cloud state")
    report.add_argument("--json", action="store_true")
    commands.add_parser("status", help="Read compact JSON state for the macOS menu bar")
    alerts = commands.add_parser(
        "alerts", help="Read the durable notification feed from local or cloud state"
    )
    alerts.add_argument("--after", type=int, default=0)
    alerts.add_argument("--limit", type=int, default=100)
    inbox = commands.add_parser("inbox", help="Read and triage alerts in local or cloud state")
    inbox_actions = inbox.add_subparsers(dest="inbox_action", required=True)
    inbox_list = inbox_actions.add_parser("list")
    inbox_list.add_argument("--filter", choices=["open", "snoozed", "reviewed"], default="open")
    inbox_list.add_argument("--before", type=int, default=0)
    inbox_list.add_argument("--limit", type=int, default=50)
    inbox_update = inbox_actions.add_parser("update")
    inbox_update.add_argument("--sequence", type=int, required=True)
    inbox_update.add_argument("--feed-id", required=True)
    inbox_update.add_argument(
        "--action", choices=["read", "unread", "review", "reopen", "snooze"], required=True
    )
    inbox_update.add_argument("--hours", type=int, default=24)
    question = commands.add_parser("ask", help="Ask about collected evidence; optional Bedrock investigation")
    question.add_argument("question")
    commands.add_parser("digest", help="Queue a daily email from the saved report")
    commands.add_parser("deliver", help="Deliver pending messages using configured preview/SES mode")
    commands.add_parser("outbox", help="Inspect delivery statuses")
    event = commands.add_parser(
        "ingest", help="Ingest a trusted EventBridge JSON fixture (local development)"
    )
    event.add_argument("file")
    worker = commands.add_parser("run", help="Run the scheduled cost collector and SQS consumer")
    worker.add_argument("--once", action="store_true")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = None
    try:
        if args.command == "setup":
            from .setup import execute

            if args.demo:
                raise ValueError("Setup is a real AWS connection operation; omit --demo.")
            print(json.dumps(execute(args)))
            return 0
        config = load_config(args.config, demo=args.demo or args.command == "demo")
        if args.command == "login":
            from .setup import login

            if config.demo:
                raise ValueError("Sign-in is unavailable in demo mode.")
            print(json.dumps(login(config.profile)))
            return 0
        if config.cloud_bucket:
            from .cloud_client import execute as cloud_execute

            print(cloud_execute(args, config))
            return 0
        store = Store(config.database)
        if config.account_id:
            store.bind_account(config.account_id)
        # Reading a saved report should not require network access or credentials.
        if args.command == "inbox":
            if args.inbox_action == "list":
                result = inbox_page(store, args.filter, args.before, args.limit)
            else:
                result = update_inbox(store, args.sequence, args.feed_id, args.action, args.hours)
            print(json.dumps(result))
            return 0
        if args.command == "alerts":
            print(json.dumps(store.alerts_after(args.after, args.limit)))
            return 0
        if args.command == "status":
            print(json.dumps(status_payload(store, config)))
            return 0
        if args.command == "report":
            snapshot = store.snapshot()
            if not snapshot:
                raise ValueError("No data yet. Run demo or sync first.")
            print(json.dumps(snapshot, indent=2) if args.json else render_report(snapshot, store.events()))
            return 0
        if args.command == "outbox":
            print(
                json.dumps(
                    [
                        {k: m[k] for k in ("id", "subject", "status", "attempts", "error")}
                        for m in store.messages()
                    ],
                    indent=2,
                )
            )
            return 0
        if args.command == "digest":
            digest(store)
            print("Daily report queued. Run deliver to process the outbox.")
            return 0
        provider = Demo() if config.demo else AWS(config)
        if args.command == "enable-savings":
            if config.demo:
                raise ValueError("Switch to an AWS account to enable recommendations.")
            print(json.dumps(provider.enable_recommendations()))
        elif args.command == "history":
            print(json.dumps(collect_history(store, provider, config)))
        elif args.command == "demo":
            sync(store, provider, config)
            ingest(store, provider, config, provider.event())
            digest(store)
            deliver(store, config, provider)
            print(render_report(store.snapshot(), store.events()))
            print(f"Email previews: {Path(config.outbox_dir).resolve()}")
        elif args.command == "sync":
            print(render_report(sync(store, provider, config), store.events()))
        elif args.command == "ask":
            print(ask(args.question, store, config, provider))
        elif args.command == "deliver":
            print(f"Processed {deliver(store, config, provider)} pending messages ({config.delivery}).")
            if store.messages(pending=True):
                return 1
        elif args.command == "ingest":
            envelope = json.loads(Path(args.file).read_text())
            print(
                "Event recorded."
                if ingest(store, provider, config, envelope)
                else "Duplicate or ignored event."
            )
        elif args.command == "run":
            with worker_lock(config.database):
                run(store, provider, config, once=args.once)
        return 0
    except KeyboardInterrupt:
        return 130
    except (ValueError, FileNotFoundError, ModuleNotFoundError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        code = getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)
        if code in {
            "TokenRetrievalError",
            "SSOTokenLoadError",
            "UnauthorizedSSOTokenError",
            "ExpiredToken",
            "ExpiredTokenException",
            "InvalidGrantException",
            "InvalidClientTokenId",
            "UnrecognizedClientException",
            "InvalidAccessKeyId",
        }:
            print(
                "AWS sign-in required: Your session expired or credentials were rejected. Reconnect in Settings.",
                file=sys.stderr,
            )
            return 1
        print(
            f"AWS operation failed ({code}). Check credentials, enrollment, region and permissions.",
            file=sys.stderr,
        )
        return 1
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    sys.exit(main())
