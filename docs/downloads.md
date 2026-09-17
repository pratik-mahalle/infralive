# Install Cloudwake

Cloudwake v0.4.0 provides a standalone **Apple silicon** app for **macOS 13+**.
Python and the AWS SDK are bundled. You do not need a source checkout, separate Python install,
or Xcode to use the downloaded app. Intel Macs currently require a source build.

## Homebrew

```sh
brew tap pratik-mahalle/tap
brew install --cask pratik-mahalle/tap/cloudwake
```

## Direct download

Download `Cloudwake-0.4.0-macos-arm64.zip` from the
[v0.4.0 release](https://github.com/pratik-mahalle/infralive/releases/tag/v0.4.0), unzip it,
and move Cloudwake.app to Applications. Open it and look for the cloud in your menu bar.

This early build is ad-hoc signed and **not Apple-notarized**. macOS may require approval in
System Settings → Privacy & Security before opening. Only approve the download if you trust
its source. Homebrew installation does not bypass Gatekeeper. The release includes SHA256SUMS.txt.

The first launch uses demo data. In Settings, choose an existing **AWS profile**, or choose
**Paste credentials** for access keys or temporary credentials. Pasted credentials are stored
in macOS Keychain after AWS verifies the account. This option needs neither SSO nor AWS CLI.
SSO profiles use your existing AWS CLI installation for browser sign-in.

The menu and Settings use macOS translucent material, blending with the desktop or windows
behind them. They follow light/dark appearance and use a solid background when Reduce
Transparency is enabled in macOS Accessibility settings.

The standalone app saves configuration, logs, and state in
`~/Library/Application Support/Cloudwake/`. Its bundled code remains read-only. Moving the app
or upgrading through Homebrew preserves account configuration and monitoring history.

## Expired AWS sign-in

AWS SSO sessions expire independently of whether your Mac is awake. Cloudwake shows
**AWS sign-in required**, keeps the last collected data visible, and pauses automatic client
polling until you reconnect. Choose **Sign in to AWS**, complete the browser sign-in, and
Cloudwake reloads your account without changing its saved connection.

The optional collector in AWS uses its own execution role; its monitoring does not depend
on the Mac's SSO session. The app cannot confirm its current health until it reconnects.
For non-SSO profiles, refresh credentials using your existing sign-in method, then click **Try again**.
For pasted temporary credentials, choose **Update credentials → Paste credentials** and import
a fresh set. For the same account and region, connecting again preserves saved history.
The sign-in button requires AWS CLI v2. Cloudwake does not extend your organization's session duration.

## Build a release

On an Apple silicon Mac with the development dependencies installed:

```sh
uv python install 3.12 --install-dir dist/python-runtime --no-bin
bash macos/build.sh
.venv/bin/python scripts/package_macos.py --python-runtime dist/python-runtime/cpython-3.12.11-macos-aarch64-none
```

Use the actual Python 3.12 directory printed by uv if its patch version differs. The packager
copies only application code, explicit runtime dependencies (with their license metadata), and
the standalone interpreter. It excludes live configuration and data, signs the bundle, runs an
offline demo check, and creates a ZIP and checksum file under `dist/release/`.

Before publishing, extract the ZIP in a different directory and run:

```sh
/path/to/Cloudwake.app/Contents/MacOS/CostBar --check-bundle
```

Also validate the event installer using the bundled interpreter:

```sh
/path/to/Cloudwake.app/Contents/Resources/Python/bin/python3.12 -B -s scripts/check_macos_setup.py /path/to/Cloudwake.app
```

These checks use disposable data and do not contact AWS or write account settings.
The packaging script runs both checks before producing a release archive.
