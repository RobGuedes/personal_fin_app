import sqlite3

import pytest

from api_fixtures import api  # noqa: F401  (re-exported so any test module can use the fixture)


@pytest.fixture(autouse=True)
def _db_guard(tmp_path_factory, monkeypatch):
    """Every test: FINANCE_DB points at a temp file (a stray connect() can never open or migrate the real
    data/finance.db), and every SQLite connection the test opened is closed afterwards (no ResourceWarning).
    Patches sqlite3.connect itself, so it also covers modules that imported finance.db.connect directly."""
    monkeypatch.setenv("FINANCE_DB", str(tmp_path_factory.mktemp("guard") / "finance.db"))
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", tracking_connect)
    yield
    for conn in opened:
        conn.close()
