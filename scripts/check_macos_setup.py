"""Exercise standalone event setup in a fresh data directory without any AWS calls."""

import json
import sys
import tempfile
import tomllib
from contextlib import chdir
from pathlib import Path
from unittest.mock import Mock, patch


def main():
    app = Path(sys.argv[1]).resolve()
    agent = app / "Contents/Resources/Agent"
    sys.path.insert(0, str(agent / "src"))
    from aws_cost_agent import setup
    from aws_cost_agent.credentials import keychain

    # Import the real macOS backend from the bundle without touching any saved secrets.
    assert keychain().priority > 0

    assert Path(setup.__file__).resolve().is_relative_to(agent)
    assert (agent / "LICENSE").read_text().startswith("Cloudwake Proprietary License\n")
    assert not list((agent / "src").rglob("*.py")), "Readable collector source must not ship"
    assert Path(setup.__file__).suffix == ".pyc"
    expected = (agent / "infra/events.json").read_text()
    assert json.loads(expected)["Resources"]["EventQueue"]["Type"] == "AWS::SQS::Queue"
    account = "123456789012"
    queue = f"https://sqs.us-east-1.amazonaws.com/{account}/aws-cost-agent-events"
    cf = Mock()
    with tempfile.TemporaryDirectory(prefix="cloudwake-setup-check-") as folder, chdir(folder):
        root = Path(folder).resolve()
        # Prevent even an accidental SDK client construction from reaching AWS.
        with (
            patch.object(setup, "session_for", side_effect=AssertionError("Unexpected AWS session")),
            patch.object(setup.boto3, "Session", side_effect=AssertionError("Unexpected AWS session")),
            patch.object(setup, "identity", return_value={"account_id": account}),
            patch.object(setup, "trail_ready", return_value=True),
            patch.object(setup, "stack_queue", side_effect=[None, queue]),
            patch.object(setup, "client", return_value=cf),
        ):
            result = setup.install_events("test", "us-east-1", account, session=object(), root=root)
        cf.create_stack.assert_called_once_with(
            StackName=setup.STACK,
            TemplateBody=expected,
            Tags=[{"Key": "Application", "Value": "CostBar"}],
        )
        cf.get_waiter.return_value.wait.assert_called_once()
        config_path = Path(result["config_path"])
        assert config_path.is_relative_to(root)
        config = tomllib.loads(config_path.read_text())
        assert config["aws"]["queues"]["us-east-1"] == queue
        assert not (root / "infra").exists()
    print("Standalone event setup verified with a fresh data directory and mocked AWS.")


if __name__ == "__main__":
    main()
