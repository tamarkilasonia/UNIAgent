import pytest

from database import database as db


@pytest.fixture(autouse=True)
def fresh_database(tmp_path, monkeypatch):
    """Give every test its own new copy of the mock database."""
    monkeypatch.setenv("UNIAGENT_DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
