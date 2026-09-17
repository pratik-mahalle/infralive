from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError, TokenRetrievalError

from aws_cost_agent import worker
from aws_cost_agent.config import Config
from aws_cost_agent.history import collect_history
from aws_cost_agent.store import Store


@pytest.mark.parametrize(
    "error",
    [
        TokenRetrievalError(provider="sso", error_msg="expired"),
        ClientError({"Error": {"Code": "ExpiredToken", "Message": "expired"}}, "test"),
    ],
)
def test_background_cost_failure_surfaces_expired_account(monkeypatch, tmp_path, error):
    store = Store(str(tmp_path / "account.sqlite3"))
    monkeypatch.setattr(worker, "sync", Mock(side_effect=error))
    sleep = Mock(side_effect=AssertionError("Expired credentials must not retry silently"))
    monkeypatch.setattr(worker.time, "sleep", sleep)
    with pytest.raises(type(error)):
        worker.run(store, Mock(), Config())
    sleep.assert_not_called()


def test_queue_expiry_reaches_worker_instead_of_being_swallowed():
    provider = Mock()
    provider.receive.side_effect = TokenRetrievalError(provider="sso", error_msg="expired")
    with pytest.raises(TokenRetrievalError):
        worker.poll(Mock(), provider, Config(queues={"us-east-1": "queue"}))


def test_history_expiry_reaches_worker_instead_of_looking_like_missing_permission(tmp_path):
    database = str(tmp_path / "account.sqlite3")
    provider = Mock()
    provider.account_id.return_value = "111111111111"
    provider.history_page.side_effect = TokenRetrievalError(provider="sso", error_msg="expired")
    with pytest.raises(TokenRetrievalError):
        collect_history(Store(database), provider, Config(database=database))


def test_non_auth_worker_failure_still_retries(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "sync", Mock(side_effect=RuntimeError("temporary outage")))
    monkeypatch.setattr(worker, "collect_history", Mock())
    monkeypatch.setattr(worker, "deliver", Mock())
    monkeypatch.setattr(worker.time, "sleep", Mock(side_effect=InterruptedError("test end")))
    with pytest.raises(InterruptedError):
        worker.run(Store(str(tmp_path / "account.sqlite3")), Mock(), Config())
