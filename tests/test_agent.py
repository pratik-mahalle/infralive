from datetime import date
from unittest.mock import Mock

import pytest

from aws_cost_agent.agent import ask
from aws_cost_agent.worker import sync


def test_offline_ask_never_calls_model(store, provider, config):
    sync(store, provider, config, date(2026, 9, 16))
    response = ask("How can we reduce spending?", store, config, provider)
    assert "Bedrock is not configured" in response
    assert "demo-rec-ec2" in response


def test_tool_use_conversation(store, provider, config):
    sync(store, provider, config, date(2026, 9, 16))
    config.model_id = "test-model"
    bedrock = Mock()
    bedrock.converse.side_effect = [
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"toolUse": {"toolUseId": "call-1", "name": "get_spending", "input": {}}}],
                }
            }
        },
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "text": "EC2 spending increased; review evidence spend:2026-09-14:Amazon EC2:us-east-1."
                        }
                    ],
                }
            }
        },
    ]
    live = Mock()
    live.client.return_value = bedrock
    result = ask("Why did compute spending increase?", store, config, live)
    assert "Evidence tools: get_spending" in result
    assert bedrock.converse.call_count == 2


def test_model_answer_without_tools_is_withheld(store, provider, config):
    sync(store, provider, config, date(2026, 9, 16))
    config.model_id = "test-model"
    live = Mock()
    live.client.return_value.converse.return_value = {
        "output": {"message": {"role": "assistant", "content": [{"text": "Invented cost $1000"}]}}
    }
    with pytest.raises(ValueError, match="without retrieving evidence"):
        ask("What is our spending?", store, config, live)


def test_agent_stops_unbounded_tool_loop(store, provider, config):
    sync(store, provider, config, date(2026, 9, 16))
    config.model_id = "test-model"
    live = Mock()
    live.client.return_value.converse.return_value = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": "call", "name": "get_changes", "input": {}}}],
            }
        }
    }
    with pytest.raises(ValueError, match="six-round limit"):
        ask("Investigate", store, config, live)
    assert live.client.return_value.converse.call_count == 6


def test_sync_keeps_service_costs_without_requesting_tag_breakdowns(store, provider, config):
    provider.allocation_tags = Mock(side_effect=AssertionError("No billing tag requests"))
    provider.team_costs = Mock(side_effect=AssertionError("No tag cost requests"))
    snapshot = sync(store, provider, config, date(2026, 9, 16))
    assert snapshot["analysis"]["top_services"]
    assert "team_spending" not in snapshot
    provider.allocation_tags.assert_not_called()
    provider.team_costs.assert_not_called()
