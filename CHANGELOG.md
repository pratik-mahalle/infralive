# Changelog

## 1.1.1 — 2026-09-17

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
