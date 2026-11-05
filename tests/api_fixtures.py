"""Fixtures for API tests: a TestClient over a temp DB synced and classified."""

import shutil

import pytest
from fastapi.testclient import TestClient

from finance.api import Workspace, create_app
from finance.classify import classify_all, load_taxonomy
from finance.config import Settings
from finance.db import connect
from finance.sync import sync
from samples import CATEGORIES_FIXTURE, MY_CPF, RULES_FIXTURE
from test_sync import TODAY, FakeClient

MUTATE = {"X-Finance-Client": "web"}


@pytest.fixture
def api(tmp_path):
    conn = connect(tmp_path / "api.db")
    sync(conn, FakeClient(), ["item-1"], today=TODAY)
    taxonomy = load_taxonomy(CATEGORIES_FIXTURE)
    classify_all(conn, taxonomy, {"rules": [{"id": "ong", "party": "ONG EXEMPLO", "category": "donations"}]}, MY_CPF)
    conn.execute("INSERT INTO manual_entries (month, pnl_line, amount, note) VALUES ('2026-10', 'income', 6420, 'Cliente Exterior')")
    conn.commit()
    rules_path = tmp_path / "rules.yaml"
    shutil.copy(RULES_FIXTURE, rules_path)
    settings = Settings(pluggy_client_id="", pluggy_client_secret="", my_cpf=MY_CPF, my_name="Test Person")
    ws = Workspace(conn=conn, taxonomy=taxonomy, rules_path=rules_path, settings=settings)
    with TestClient(create_app(workspace_factory=lambda: ws), base_url="http://localhost") as client:
        yield client
    conn.close()

