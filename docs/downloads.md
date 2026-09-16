# Install Cloudwake

Cloudwake v0.3.0 provides a standalone **Apple silicon** app for **macOS 13+**.
Python and the AWS SDK are bundled. You do not need a source checkout, separate Python install,
or Xcode to use the downloaded app. Intel Macs currently require a source build.

## Homebrew

```sh
brew install --cask pratik-mahalle/tap/cloudwake
```

## Direct download

Download `Cloudwake-0.3.0-macos-arm64.zip` from the
[v0.3.0 release](https://github.com/pratik-mahalle/infralive/releases/tag/v0.3.0), unzip it,
and move Cloudwake.app to Applications. Open it and look for the cloud in your menu bar.

This early build is ad-hoc signed and **not Apple-notarized**. macOS may require approval in
System Settings → Privacy & Security before opening. Only approve the download if you trust
its source. Homebrew installation does not bypass Gatekeeper. The release includes SHA256SUMS.txt.

The first launch uses demo data. To connect AWS, configure an AWS CLI profile, then choose
it in Cloudwake Settings. AWS SSO sign-in uses your existing AWS CLI installation.

The standalone app saves configuration, logs, and state in
`~/Library/Application Support/Cloudwake/`. Its bundled code remains read-only. Moving the app
or upgrading through Homebrew preserves account configuration and monitoring history.

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

The smoke check uses disposable synthetic data and does not contact AWS or write account settings.
