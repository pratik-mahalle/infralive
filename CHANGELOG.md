# Changelog

## 1.2.2 — 2026-09-18

- Redesign the Mac panel with compact account controls, bottom navigation, and a smaller spending card with an inline daily chart.
- Refine activity, savings, service, and inbox rows for light and dark macOS appearances.
- Keep credits, net balance, forecasts, and detailed daily spending available; retain cloud companion alerts and multi-account monitoring.
- Move CI to Codemagic and remove the GitHub Actions workflow.

## 1.2.1 — 2026-09-18

- Move public downloads and setup documentation to a release-only repository; application source stays private.
- Apply proprietary licensing to this version while preserving prior MIT grants and third-party license notices.
- Package the collector as bytecode and keep readable application source out of the Mac download.
- Preserve the cloud companion, redesigned interface, AWS connections, and monitoring history.

## 1.2.0 — 2026-09-18

- Introduce a cloud mascot and compact companion alerts with account-specific Review and one-hour inbox snooze actions.
- Keep native macOS banners for background delivery; show companion bubbles during foreground use or on a notification click.
- Add a companion preference and a safe preview in notification settings.
- Refresh the menu with clearer navigation, grouped spending cards, a quieter footer, and compact account setup.
- Keep notification actions tied to the original account and reject snoozes from a replaced inbox.

## 1.1.1 — 2026-09-17

- Simplify Overview to AWS service costs; remove Project and Owner views and their extra billing-tag API requests.

- Open AWS connection setup directly on a fresh install instead of loading demo spending.
- Show the connection form directly in the menu until an account is connected.
- Replace the setup placeholder with the verified account and return to setup after removing the last account.
- Preserve existing saved connections and monitoring preferences.

## 1.1.0 — 2026-09-17

- Connect multiple AWS accounts and switch between their spending, activity, savings, and inboxes.
- Monitor accounts concurrently; switching views leaves other account workers running.
- Name, pause, resume, and remove connections independently in Settings.
- Restore account selection and each local monitor's enabled state on app relaunch.
- Include account names and IDs in Mac notification banners, with separate notification cursors.
- Migrate the existing single-account connection without moving its data or credentials.
- Surface expired background credentials for the affected account instead of silently retrying them.

## 1.0.1 — 2026-09-17

- Release Cloudwake under the MIT License.
- Include the license in the Python package and standalone Mac app.
- No changes to AWS collection, notifications, or account connections.

## 1.0.0 — 2026-09-17

- AWS spending, forecasts, credits, resource activity, and savings in a native Mac menu bar app.
- Cost grouping by Project and Owner, including Unassigned spending.
- Resource creation alerts, unused-resource observations, and a persistent notification inbox.
- AWS profile connections and non-SSO credential import backed by macOS Keychain.
- Expired-session recovery that preserves the last collected data.
- Native translucent panels that follow macOS appearance and accessibility settings.
- Optional monitoring in the user's AWS account while the Mac is asleep.
- Standalone Apple silicon download and Homebrew installation for macOS 13+.

The app is ad-hoc signed and not Apple-notarized. Weekly email, GCP, and Azure are not included.
AWS billing and activity coverage retain the limits described in the operation reference.
