# Install Cloudwake

Cloudwake v1.2.1 provides a standalone **Apple silicon** app for **macOS 13+**.
Python and the AWS SDK are bundled. You do not need a source checkout, separate Python install,
or Xcode to use the downloaded app. The current download does not support Intel Macs.

## Homebrew

```sh
brew tap pratik-mahalle/tap
brew install --cask pratik-mahalle/tap/cloudwake
```

## Direct download

Download `Cloudwake-1.2.1-macos-arm64.zip` from the
[v1.2.1 release](https://github.com/pratik-mahalle/cloudwake-releases/releases/tag/v1.2.1), unzip it,
and move Cloudwake.app to Applications. Open it and look for the cloud in your menu bar.

This build is ad-hoc signed and **not Apple-notarized**. macOS may require approval in
System Settings → Privacy & Security before opening. Only approve the download if you trust
its source. Homebrew installation does not bypass Gatekeeper. The release includes SHA256SUMS.txt.

The first launch opens **Connect your AWS account** directly, without loading demo spending.
Choose an existing **AWS profile**, or choose
**Paste credentials** for access keys or temporary credentials. Pasted credentials are stored
in macOS Keychain after AWS verifies the account. This option needs neither SSO nor AWS CLI.
SSO profiles use your existing AWS CLI installation for browser sign-in.

The menu and Settings use macOS translucent material, blending with the desktop or windows
behind them. They follow light/dark appearance and use a solid background when Reduce
Transparency is enabled in macOS Accessibility settings.

The standalone app saves configuration, logs, and state in
`~/Library/Application Support/Cloudwake/`. Its bundled code remains read-only. Moving the app
or upgrading through Homebrew preserves account configuration and monitoring history.

## Multiple accounts

In Settings, use **Add or reconnect an account** for each AWS account and optionally name it.
New local connections start monitoring automatically. Use the account picker to switch costs,
activity, savings and inboxes; other accounts continue monitoring. **Your accounts** lets you
pause, resume, rename or remove individual connections. The menu bar amount is for the selected
account. Existing connections migrate automatically when upgrading from v1.0.x.

To update an existing Homebrew installation, quit Cloudwake, then run:

```sh
brew update
brew upgrade --cask pratik-mahalle/tap/cloudwake
```

Local monitoring needs an awake Mac with the app open. Always-on monitoring is configured
separately in each AWS account. Removing a connection does not delete credentials, local history,
or its AWS deployment.

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

## Cloud companion

Enable Mac notifications in Settings. A cloud companion appears for alerts while using Cloudwake
or when you click a native notification. Background alerts use macOS banners and respect Focus.
Review opens the alert's account inbox. In 1 hour snoozes it in that inbox; it does not schedule a
new desktop banner. Use Settings → Mac notifications → Preview to try the bubble.

## License and support

Cloudwake v1.2.1 and later are proprietary. The official app is currently available for personal
and internal business use at no charge under the license included with the application.
Earlier MIT releases retain their original terms. Third-party dependencies keep their licenses.

[Release notes](https://github.com/pratik-mahalle/cloudwake-releases/releases) ·
[Support](https://github.com/pratik-mahalle/cloudwake-releases/issues)
