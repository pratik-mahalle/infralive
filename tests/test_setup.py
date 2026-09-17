import json
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from aws_cost_agent import setup
from aws_cost_agent.cli import main

ACCOUNT = "123456789012"
QUEUE = f"https://sqs.us-east-1.amazonaws.com/{ACCOUNT}/aws-cost-agent-events"


def aws_error(code="AccessDeniedException", message="Denied"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "test")


@pytest.fixture
def aws(monkeypatch):
    clients = {
        name: Mock()
        for name in (
            "sts",
            "ce",
            "cost-optimization-hub",
            "cloudtrail",
            "cloudformation",
            "compute-optimizer",
        )
    }
    clients["sts"].get_caller_identity.return_value = {
        "Account": ACCOUNT,
        "Arn": f"arn:aws:iam::{ACCOUNT}:role/observer",
    }
    clients["cloudtrail"].describe_trails.return_value = {
        "trailList": [{"HomeRegion": "us-east-1", "TrailARN": "trail", "IsMultiRegionTrail": True}]
    }
    clients["cloudtrail"].get_trail_status.return_value = {"IsLogging": True}
    clients["cloudtrail"].get_event_selectors.return_value = {
        "EventSelectors": [{"IncludeManagementEvents": True, "ReadWriteType": "WriteOnly"}]
    }
    clients["compute-optimizer"].get_enrollment_status.return_value = {"status": "Active"}
    clients["cloudformation"].describe_stacks.return_value = stack()
    monkeypatch.setattr(setup, "client", lambda session, service, region=None: clients[service])
    return clients


def stack():
    return {
        "Stacks": [
            {"StackStatus": "CREATE_COMPLETE", "Outputs": [{"OutputKey": "QueueUrl", "OutputValue": QUEUE}]}
        ]
    }


def test_check_detects_account_but_does_not_change_aws(aws):
    result = setup.check("test", "us-east-1", session=object())
    assert result["account_id"] == ACCOUNT
    assert all(c["ready"] for c in result["checks"])
    aws["cloudformation"].create_stack.assert_not_called()


def test_permission_errors_are_not_reported_as_enabled(aws):
    aws["ce"].get_cost_and_usage.side_effect = aws_error()
    aws["cost-optimization-hub"].list_recommendations.side_effect = aws_error()
    aws["cloudformation"].describe_stacks.side_effect = aws_error()
    result = setup.check("test", "us-east-1", session=object())
    assert [c["ready"] for c in result["checks"]] == [False, False, True, True, False]
    assert "Permission needed" in result["checks"][0]["detail"]


def test_wrong_account_never_writes_config_or_deploys(aws, tmp_path):
    with pytest.raises(ValueError, match="account changed"):
        setup.install_events("test", "us-east-1", "999999999999", session=object(), root=tmp_path)
    aws["cloudformation"].create_stack.assert_not_called()
    assert not (tmp_path / "data").exists()


def test_connection_imports_queue_and_preserves_customization(aws, tmp_path):
    result = setup.connect("test", "us-east-1", ACCOUNT, session=object(), root=tmp_path)
    path = Path(result["config_path"])
    value = tomllib.loads(path.read_text())
    assert value["aws"]["queues"]["us-east-1"] == QUEUE
    assert value["notifications"]["delivery"] == "preview"
    path.write_text(path.read_text().replace("idle_monthly_savings = 25", "idle_monthly_savings = 90"))
    setup.connect("test", "us-east-1", ACCOUNT, session=object(), root=tmp_path)
    assert tomllib.loads(path.read_text())["agent"]["idle_monthly_savings"] == 90
    assert path.stat().st_mode & 0o777 == 0o600


def test_cost_only_connection_survives_missing_cloudformation_permission(aws, tmp_path):
    aws["cloudformation"].describe_stacks.side_effect = aws_error()
    result = setup.connect("test", "us-east-1", ACCOUNT, session=object(), root=tmp_path)
    assert "Permission" in result["warning"]
    assert tomllib.loads(Path(result["config_path"]).read_text())["aws"]["queues"] == {}


def test_generated_configs_escape_values_and_isolate_accounts(tmp_path):
    first = setup.write_connection('profile"\\\n', "us-east-1", ACCOUNT, root=tmp_path)
    second = setup.write_connection('profile"\\\n', "us-east-1", "999999999999", root=tmp_path)
    assert first != second
    assert tomllib.loads(Path(first).read_text())["aws"]["profile"] == 'profile"\\\n'


def test_install_requires_active_write_trail(aws, tmp_path):
    aws["cloudtrail"].get_trail_status.return_value = {"IsLogging": False}
    with pytest.raises(ValueError, match="CloudTrail"):
        setup.install_events("test", "us-east-1", ACCOUNT, session=object(), root=tmp_path)
    aws["cloudformation"].create_stack.assert_not_called()


@pytest.mark.parametrize("unrelated_template", [False, True])
def test_install_uses_installed_template_from_separate_data_directory(
    aws, tmp_path, monkeypatch, unrelated_template
):
    cf = aws["cloudformation"]
    cf.describe_stacks.side_effect = [aws_error("ValidationError", "Stack does not exist"), stack()]
    monkeypatch.chdir(tmp_path)
    if unrelated_template:
        (tmp_path / "infra").mkdir()
        (tmp_path / "infra/events.json").write_text('{"Resources":{}}')
    expected = (Path(__file__).resolve().parents[1] / "infra/events.json").read_text()
    result = setup.install_events("test", "us-east-1", ACCOUNT, session=object(), root=tmp_path)
    cf.create_stack.assert_called_once_with(
        StackName=setup.STACK,
        TemplateBody=expected,
        Tags=[{"Key": "Application", "Value": "CostBar"}],
    )
    assert tomllib.loads(Path(result["config_path"]).read_text())["aws"]["queues"]["us-east-1"] == QUEUE


def test_existing_stack_is_reused_without_mutation(aws, tmp_path):
    setup.install_events("test", "us-east-1", ACCOUNT, session=object(), root=tmp_path)
    aws["cloudformation"].create_stack.assert_not_called()
    aws["cloudformation"].update_stack.assert_not_called()


def test_stack_failure_never_claims_notifications_installed(aws, tmp_path):
    cf = aws["cloudformation"]
    cf.describe_stacks.return_value = {"Stacks": [{"StackStatus": "ROLLBACK_COMPLETE"}]}
    with pytest.raises(ValueError, match="ROLLBACK_COMPLETE"):
        setup.install_events("test", "us-east-1", ACCOUNT, session=object(), root=tmp_path)
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    "selector,expected",
    [
        ({"EventSelectors": [{"IncludeManagementEvents": True, "ReadWriteType": "ReadOnly"}]}, False),
        (
            {
                "AdvancedEventSelectors": [
                    {
                        "FieldSelectors": [
                            {"Field": "eventCategory", "Equals": ["Management"]},
                            {"Field": "readOnly", "Equals": ["false"]},
                        ]
                    }
                ]
            },
            True,
        ),
        (
            {
                "AdvancedEventSelectors": [
                    {
                        "FieldSelectors": [
                            {"Field": "eventCategory", "Equals": ["Management"]},
                            {"Field": "eventName", "Equals": ["CreateBucket"]},
                        ]
                    }
                ]
            },
            False,
        ),
    ],
)
def test_trail_check_does_not_claim_partial_or_read_only_coverage(selector, expected):
    assert setup.logs_writes(selector) == expected


def test_setup_runs_without_config_and_demo_cannot_contact_aws(monkeypatch, capsys):
    operation = Mock(return_value={"profiles": ["test"], "regions": ["us-east-1"]})
    monkeypatch.setattr(setup, "execute", operation)
    assert main(["setup", "profiles"]) == 0
    assert json.loads(capsys.readouterr().out)["profiles"] == ["test"]
    assert main(["--demo", "setup", "profiles"]) == 1
    assert operation.call_count == 1


def test_sso_uses_literal_profile_and_no_shell(monkeypatch):
    monkeypatch.setattr(setup.shutil, "which", lambda _: "/usr/bin/aws")
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(setup.subprocess, "run", run)
    args = SimpleNamespace(setup_action="login", profile="literal $(command)")
    assert setup.execute(args) == {"signed_in": True}
    assert run.call_args.args[0] == ["/usr/bin/aws", "sso", "login", "--profile", "literal $(command)"]
    assert "shell" not in run.call_args.kwargs


def test_compute_optimizer_must_be_active_for_idle_readiness(aws):
    aws["compute-optimizer"].get_enrollment_status.return_value = {"status": "Inactive"}
    result = setup.check("test", "us-east-1", session=object())
    finding = next(c for c in result["checks"] if c["id"] == "savings")
    assert not finding["ready"]
    assert "Compute Optimizer" in finding["detail"]


def test_reconnect_rejects_config_with_changed_profile(tmp_path):
    path = Path(setup.write_connection("test", "us-east-1", ACCOUNT, root=tmp_path))
    path.write_text(path.read_text().replace('profile = "test"', 'profile = "other"'))
    with pytest.raises(ValueError, match="customized"):
        setup.write_connection("test", "us-east-1", ACCOUNT, root=tmp_path)


def test_non_ascii_profile_is_valid_toml(tmp_path):
    path = Path(setup.write_connection("engineering-☁️", "us-east-1", ACCOUNT, root=tmp_path))
    assert tomllib.loads(path.read_text())["aws"]["profile"] == "engineering-☁️"


def test_connected_login_uses_saved_profile_without_cloud_access(monkeypatch, tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text(
        '[aws]\nprofile = "team-sso"\naccount_id = "123456789012"\n'
        '[cloud]\nstate_bucket = "example-state"\nfunction_name = "cloudpulse-monitor"\nregion = "us-east-1"\n'
    )
    login = Mock(return_value={"signed_in": True})
    monkeypatch.setattr(setup, "login", login)
    from aws_cost_agent import cloud_client

    cloud = Mock(side_effect=AssertionError("Login must not read cloud state with expired credentials"))
    monkeypatch.setattr(cloud_client, "execute", cloud)
    before = config.read_bytes()
    assert main(["--config", str(config), "login"]) == 0
    login.assert_called_once_with("team-sso")
    cloud.assert_not_called()
    assert config.read_bytes() == before
    assert json.loads(capsys.readouterr().out)["signed_in"]


def test_demo_login_never_starts_aws_sign_in(monkeypatch, capsys):
    login = Mock()
    monkeypatch.setattr(setup, "login", login)
    assert main(["--demo", "login"]) == 1
    login.assert_not_called()
    assert "unavailable in demo" in capsys.readouterr().err


def test_expired_sso_returns_actionable_error(monkeypatch, capsys):
    from botocore.exceptions import TokenRetrievalError

    monkeypatch.setattr(
        setup, "execute", Mock(side_effect=TokenRetrievalError(provider="sso", error_msg="expired"))
    )
    assert main(["setup", "profiles"]) == 1
    error = capsys.readouterr().err
    assert "AWS sign-in required:" in error
    assert "Traceback" not in error


@pytest.mark.parametrize("folder", ["homebrew", ".homebrew", ".local"])
def test_sso_finds_user_install_with_minimal_finder_path(monkeypatch, tmp_path, folder):
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    monkeypatch.delenv("HOMEBREW_PREFIX", raising=False)
    monkeypatch.setattr(setup.shutil, "which", lambda _: None)
    monkeypatch.setattr(setup.Path, "home", lambda: tmp_path)
    executable = tmp_path / folder / "bin/aws"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    # Isolate system installations, so this also works on CI machines with AWS CLI.
    actual_is_file = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda p: p.is_relative_to(tmp_path) and actual_is_file(p))
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(setup.subprocess, "run", run)
    assert setup.login("team-sso") == {"signed_in": True}
    assert run.call_args.args[0] == [str(executable), "sso", "login", "--profile", "team-sso"]
    assert "shell" not in run.call_args.kwargs


def test_cli_discovery_respects_custom_homebrew_prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(setup.shutil, "which", lambda _: None)
    monkeypatch.setenv("HOMEBREW_PREFIX", str(tmp_path / "custom prefix"))
    executable = tmp_path / "custom prefix/bin/aws"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    assert setup.aws_cli_executable() == str(executable)
    monkeypatch.setattr(setup.shutil, "which", lambda _: "/preferred/bin/aws")
    assert setup.aws_cli_executable() == "/preferred/bin/aws"


def test_missing_or_non_executable_cli_is_actionable(monkeypatch, tmp_path):
    monkeypatch.setattr(setup.shutil, "which", lambda _: None)
    monkeypatch.delenv("HOMEBREW_PREFIX", raising=False)
    monkeypatch.setattr(setup.Path, "home", lambda: tmp_path)
    executable = tmp_path / "homebrew/bin/aws"
    executable.parent.mkdir(parents=True)
    executable.write_text("not executable")
    actual_is_file = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda p: p.is_relative_to(tmp_path) and actual_is_file(p))
    run = Mock()
    monkeypatch.setattr(setup.subprocess, "run", run)
    with pytest.raises(ValueError, match="Install AWS CLI v2"):
        setup.login("team-sso")
    run.assert_not_called()
