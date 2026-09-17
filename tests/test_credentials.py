import io
import json
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from aws_cost_agent import credentials, setup
from aws_cost_agent.cli import main

ACCOUNT = "123456789012"
VALUES = {"aws_access_key_id": "AKIA" + "A" * 16, "aws_secret_access_key": "s" * 40}


@pytest.mark.parametrize(
    "text",
    [
        json.dumps(VALUES),
        json.dumps(
            {
                "Credentials": {
                    "AccessKeyId": VALUES["aws_access_key_id"],
                    "SecretAccessKey": VALUES["aws_secret_access_key"],
                }
            }
        ),
        "\n".join(f'export {key.upper()}="{value}"' for key, value in VALUES.items()),
        "[my-profile]\n" + "\n".join(f"{key} = {value}" for key, value in VALUES.items()),
    ],
)
def test_supported_paste_formats(text):
    assert credentials.parse_credentials(text) == VALUES


@pytest.mark.parametrize(
    "text",
    [
        'export AWS_SECRET_ACCESS_KEY="$(touch /tmp/should-not-run)"',
        json.dumps({**VALUES, "aws_session_token": "$(command)"}),
        "export AWS_ACCESS_KEY_ID=$(cat ~/.aws/credentials)",
        json.dumps({**VALUES, "AccessKeyId": VALUES["aws_access_key_id"]}),
        'private-secret-marker="unterminated',
        "x" * 32769,
        json.dumps({"Credentials": []}),
    ],
)
def test_invalid_input_errors_never_echo_pasted_text(text):
    with pytest.raises(ValueError) as failure:
        credentials.parse_credentials(text)
    assert "private-secret-marker" not in str(failure.value)
    assert "$(" not in str(failure.value)
    assert VALUES["aws_secret_access_key"] not in str(failure.value)


def test_temporary_credentials_require_token_and_check_expiration():
    temporary = {**VALUES, "aws_access_key_id": "ASIA" + "A" * 16}
    with pytest.raises(ValueError, match="AWS_SESSION_TOKEN"):
        credentials.parse_credentials(json.dumps(temporary))
    temporary["aws_session_token"] = "token/with+symbols="
    assert credentials.parse_credentials(json.dumps(temporary)) == temporary
    with pytest.raises(ValueError, match="expired"):
        credentials.parse_credentials(json.dumps({**temporary, "Expiration": "2000-01-01T00:00:00Z"}))


@pytest.fixture
def imported(monkeypatch, tmp_path):
    keychain = Mock()
    monkeypatch.setattr(credentials, "keychain", lambda: keychain)
    session = Mock()
    monkeypatch.setattr(credentials.boto3, "Session", Mock(return_value=session))
    monkeypatch.setattr(setup, "validate_region", Mock())
    monkeypatch.setattr(setup, "identity", Mock(return_value={"account_id": ACCOUNT}))
    return keychain, session, tmp_path


def test_import_verifies_identity_and_keeps_secrets_only_in_keychain(imported):
    keychain, session, root = imported
    result = credentials.import_credentials(json.dumps(VALUES), "us-east-1", root)
    setup.identity.assert_called_once_with(session)
    keychain.set_password.assert_called_once_with(credentials.SERVICE, ACCOUNT, json.dumps(VALUES))
    assert result == {"profile": credentials.PREFIX + ACCOUNT, "account_id": ACCOUNT, "temporary": False}
    assert credentials.saved_profiles(root) == [result["profile"]]
    for path in root.rglob("*"):
        if path.is_file():
            assert VALUES["aws_secret_access_key"] not in path.read_text()
            assert VALUES["aws_access_key_id"] not in path.read_text()


def test_failed_aws_validation_never_overwrites_saved_credentials(imported, monkeypatch):
    keychain, _, root = imported
    monkeypatch.setattr(
        setup,
        "identity",
        Mock(side_effect=ClientError({"Error": {"Code": "InvalidClientTokenId"}}, "GetCallerIdentity")),
    )
    with pytest.raises(ClientError):
        credentials.import_credentials(json.dumps(VALUES), "us-east-1", root)
    keychain.set_password.assert_not_called()
    assert not (root / "data").exists()


def test_managed_session_never_falls_back_to_ambient_credentials(imported):
    keychain, session, _ = imported
    keychain.get_password.return_value = None
    with pytest.raises(ValueError, match="Saved credentials are missing"):
        credentials.session_for(credentials.PREFIX + ACCOUNT, "us-east-1")
    credentials.boto3.Session.assert_not_called()
    keychain.get_password.return_value = json.dumps(VALUES)
    assert credentials.session_for(credentials.PREFIX + ACCOUNT, "us-east-1") is session
    credentials.boto3.Session.assert_called_once_with(region_name="us-east-1", **VALUES)


def test_profile_session_preserves_sdk_chain(imported):
    keychain, _, _ = imported
    credentials.session_for("my-static-profile", "eu-west-1")
    keychain.get_password.assert_not_called()
    credentials.boto3.Session.assert_called_once_with(
        profile_name="my-static-profile", region_name="eu-west-1"
    )


def test_cli_import_reads_stdin_without_returning_credentials(imported, monkeypatch, capsys):
    _, _, root = imported
    monkeypatch.chdir(root)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(VALUES)))
    assert main(["setup", "import-credentials", "--region", "us-east-1"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["profile"] == credentials.PREFIX + ACCOUNT
    assert VALUES["aws_secret_access_key"] not in output.out + output.err


def test_keychain_failure_is_redacted_and_has_no_plaintext_fallback(imported, capsys, monkeypatch):
    keychain, _, root = imported
    keychain.set_password.side_effect = RuntimeError(VALUES["aws_secret_access_key"])
    monkeypatch.chdir(root)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(VALUES)))
    assert main(["setup", "import-credentials", "--region", "us-east-1"]) == 1
    output = capsys.readouterr()
    assert VALUES["aws_secret_access_key"] not in output.out + output.err
    assert "Keychain" in output.err
    assert not (root / "data").exists()
