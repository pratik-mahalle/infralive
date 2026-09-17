"""Explicit credential import. Never execute pasted shell text or persist plaintext secrets."""

import json
import re
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path

import boto3

PREFIX = "cloudwake-keychain-"
SERVICE = "dev.cloudwake.aws-credentials"
MAX_INPUT = 32768
ALIASES = {
    "AWS_ACCESS_KEY_ID": "aws_access_key_id",
    "AccessKeyId": "aws_access_key_id",
    "AWS_SECRET_ACCESS_KEY": "aws_secret_access_key",
    "SecretAccessKey": "aws_secret_access_key",
    "AWS_SESSION_TOKEN": "aws_session_token",
    "SessionToken": "aws_session_token",
    "Expiration": "expiration",
}


def parse_credentials(text):
    if not text.strip() or len(text.encode()) > MAX_INPUT:
        raise ValueError("Paste AWS credentials (up to 32 KB), then try again.")
    try:
        if text.lstrip().startswith("{"):
            values = json.loads(text)
            if isinstance(values, dict) and "Credentials" in values:
                values = values["Credentials"]
            if not isinstance(values, dict):
                raise ValueError
        else:
            values = {}
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or re.fullmatch(r"\[[^\[\]]+\]", line):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                key, separator, raw = line.partition("=")
                key = key.strip()
                if not separator or key in values:
                    raise ValueError
                parts = shlex.split(raw, comments=True)
                if len(parts) != 1:
                    raise ValueError
                values[key] = parts[0]
        result = {}
        for key, value in values.items():
            name = ALIASES.get(key, key)
            if name not in {"aws_access_key_id", "aws_secret_access_key", "aws_session_token", "expiration"}:
                continue
            if name in result or not isinstance(value, str):
                raise ValueError
            result[name] = value.strip()
        if not re.fullmatch(r"[A-Z0-9]{16,128}", result.get("aws_access_key_id", "")):
            raise ValueError
        if not re.fullmatch(r"[A-Za-z0-9/+=]{40}", result.get("aws_secret_access_key", "")):
            raise ValueError
        token = result.get("aws_session_token", "")
        if token and not re.fullmatch(r"[A-Za-z0-9/+=_-]+", token):
            raise ValueError
        if result["aws_access_key_id"].startswith("ASIA") and not token:
            raise ValueError("Temporary credentials also need AWS_SESSION_TOKEN.")
        if not token:
            result.pop("aws_session_token", None)
        if result.get("expiration"):
            expiry = datetime.fromisoformat(result["expiration"].replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                raise ValueError
            if expiry <= datetime.now(UTC):
                raise ValueError("AWS sign-in required: These credentials have expired. Paste a fresh set.")
        else:
            result.pop("expiration", None)
        return result
    except (ValueError, TypeError, AttributeError) as error:
        # Never include raw parser exceptions: JSON/shlex errors may contain secrets.
        if str(error) in {
            "Temporary credentials also need AWS_SESSION_TOKEN.",
            "AWS sign-in required: These credentials have expired. Paste a fresh set.",
        }:
            raise ValueError(str(error)) from None
        raise ValueError(
            "Use AWS export lines, a credentials-file section, or credential JSON with an access key and secret key."
        ) from None


def keychain():
    if sys.platform != "darwin":
        raise ValueError("Pasted credentials require macOS Keychain. Use an AWS profile on other systems.")
    # Pin the OS backend; never fall back to a plaintext or user-configured backend.
    from ctypes import c_long, c_void_p

    from keyring.backends.macOS import Keyring, api

    class UpdatingKeyring(Keyring):
        def set_password(self, service, username, password):
            # The library's default setter deletes before adding. Update in place so
            # a failed replacement cannot remove a working credential set.
            update = api._sec.SecItemUpdate
            update.argtypes = (c_void_p, c_void_p)
            update.restype = api.OS_status
            query = api.create_query(
                kSecClass=api.k_("kSecClassGenericPassword"),
                kSecAttrService=service,
                kSecAttrAccount=username,
            )
            create_data = api._found.CFDataCreate
            create_data.argtypes = (c_void_p, c_void_p, c_long)
            create_data.restype = c_void_p
            encoded = password.encode("utf-8")
            data = c_void_p(create_data(None, encoded, len(encoded)))
            attributes = api.create_query(kSecValueData=data)
            release = api._found.CFRelease
            release.argtypes = (c_void_p,)
            release.restype = None
            try:
                status = update(query, attributes)
            finally:
                for value in (attributes, data, query):
                    release(value)
            if status == api.error.item_not_found:
                return super().set_password(service, username, password)
            api.Error.raise_for_status(status)

    return UpdatingKeyring()


def managed_account(profile):
    if profile and profile.startswith(PREFIX):
        account = profile[len(PREFIX) :]
        if not re.fullmatch(r"\d{12}", account):
            raise ValueError("Invalid saved credential connection. Reconnect in Settings.")
        return account
    return None


def session_for(profile, region):
    if account := managed_account(profile):
        try:
            saved = keychain().get_password(SERVICE, account)
        except Exception:
            raise ValueError("Unlock macOS Keychain and allow Cloudwake access, then try again.") from None
        if not saved:
            raise ValueError(
                "AWS sign-in required: Saved credentials are missing. Paste credentials in Settings."
            )
        values = parse_credentials(saved)
        values.pop("expiration", None)
        return boto3.Session(region_name=region, **values)
    return boto3.Session(profile_name=profile, region_name=region)


def saved_profiles(root=Path(".")):
    folder = root / "data" / "credential-profiles"
    return [
        PREFIX + path.stem for path in sorted(folder.glob("*.json")) if re.fullmatch(r"\d{12}", path.stem)
    ]


def import_credentials(text, region, root=Path(".")):
    from .setup import identity, validate_region

    validate_region(region)
    values = parse_credentials(text)
    session = boto3.Session(region_name=region, **{k: v for k, v in values.items() if k != "expiration"})
    account = identity(session)["account_id"]
    # Only a successfully authenticated account can replace its saved credentials.
    try:
        keychain().set_password(SERVICE, account, json.dumps(values))
    except Exception:
        raise ValueError(
            "Could not save credentials in macOS Keychain. Unlock Keychain and try again."
        ) from None
    folder = root / "data" / "credential-profiles"
    folder.mkdir(parents=True, exist_ok=True)
    # This index contains account identifiers only, never credentials.
    (folder / f"{account}.json").write_text(json.dumps({"account_id": account}))
    return {
        "profile": PREFIX + account,
        "account_id": account,
        "temporary": bool(values.get("aws_session_token")),
    }
