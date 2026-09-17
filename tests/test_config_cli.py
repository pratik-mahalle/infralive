import json
from pathlib import Path

import pytest

from aws_cost_agent.cli import main
from aws_cost_agent.config import load_config


def test_ses_requires_sender_and_recipients(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[notifications]\ndelivery = "ses"\n')
    with pytest.raises(ValueError, match="requires"):
        load_config(str(path))


def test_cross_account_requires_external_id(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[aws]\nrole_arn = "arn:aws:iam::123456789012:role/Observer"\n')
    with pytest.raises(ValueError, match="external_id"):
        load_config(str(path))


def test_demo_cannot_accidentally_send_email(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config.toml"
    path.write_text('[notifications]\ndelivery = "ses"\n[ai]\nbedrock_model_id = "live-model"\n')
    config = load_config(str(path), demo=True)
    assert config.delivery == "preview"
    assert config.model_id == ""
    assert config.database == "data/demo.sqlite3"


def test_cli_demo_then_offline_report(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["demo"]) == 0
    assert "SYNTHETIC DATA" in capsys.readouterr().out
    assert main(["--demo", "report", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["demo"] is True
    assert report["account_id"] == "123456789012"
    previews = list((tmp_path / "data/demo-email-preview").glob("*.eml"))
    assert len(previews) >= 3
    assert all("[DEMO]" in p.read_text() for p in previews)


def test_report_before_sync_is_actionable(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["--demo", "report"]) == 1
    assert "No data yet" in capsys.readouterr().err


def test_infrastructure_references_resolve():
    root = Path(__file__).resolve().parents[1] / "infra"
    for name in ("events.json", "observer-role.json"):
        template = json.loads((root / name).read_text())
        known = set(template["Resources"]) | set(template.get("Parameters", {}))

        def visit(node, known=known, template=template):
            if isinstance(node, dict):
                if "Ref" in node:
                    assert node["Ref"] in known or node["Ref"].startswith("AWS::")
                if "Fn::GetAtt" in node:
                    assert node["Fn::GetAtt"][0] in template["Resources"]
                for child in node.values():
                    visit(child)
            elif isinstance(node, list):
                for child in node:
                    visit(child)

        visit(template)
