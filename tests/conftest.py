import pytest

from aws_cost_agent.config import Config
from aws_cost_agent.demo import Demo
from aws_cost_agent.store import Store


@pytest.fixture
def config(tmp_path):
    return Config(database=str(tmp_path / "agent.sqlite3"), outbox_dir=str(tmp_path / "mail"), demo=True)


@pytest.fixture
def store(config):
    result = Store(config.database)
    yield result
    result.close()


@pytest.fixture
def provider():
    return Demo()
