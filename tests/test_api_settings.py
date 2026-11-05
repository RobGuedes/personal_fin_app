"""Ajustes API: background sync runner, transfer audit, rules, manual entries."""

import json
import re
import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient

from api_fixtures import MUTATE
from finance import aggregate as agg
from finance.api import create_app
from finance.api.sync_runner import SyncRunner
from finance.binance_sync import BinanceSyncResult
from finance.pipeline import SyncReport
from finance.sync import SyncResult, sync
from test_sync import TODAY, FakeClient

P = "/api/v1"
DOCS = re.compile(r"(?<!\d)(\d{11}|\d{14}|\d{3}\.\d{3}\.\d{3}-\d{2}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})(?!\d)")
WAIT = 10  # seconds; Events are set long before this in a passing run


def _ws(client):
    return client.app.dependency_overrides[next(iter(client.app.dependency_overrides))]()


def _no_leak(body) -> None:
    text = json.dumps(body, ensure_ascii=False)
    assert "raw_json" not in text and not DOCS.search(text), text


@pytest.fixture
def make_client(api):
    """Build a second client over the same workspace with an injected runner; joins the runner on exit."""
    ws = _ws(api)
    made = []

    def make(runner):
        client = TestClient(create_app(workspace_factory=lambda: ws, sync_runner=runner), base_url="http://localhost")
        client.__enter__()
        made.append((client, runner))
        return client

    yield make
    for client, runner in made:
        assert runner.join(WAIT), "sync thread still running"
        client.__exit__(None, None, None)


class Gate:
    """A fake pipeline that stops at each step until the test releases it."""

    def __init__(self, steps=("Bancos (Pluggy)", "Binance", "Classificação")):
        self.steps = steps
        self.reached = {s: threading.Event() for s in steps}
        self.release = {s: threading.Event() for s in steps}
        self.conns = []

    def __call__(self, conn, settings, progress):
        self.conns.append(conn)
        for s in self.steps:
            progress(s)
            self.reached[s].set()
            assert self.release[s].wait(WAIT)
        return SyncReport(pluggy=SyncResult(items_synced=3, inserted=2, updated=1, deleted=0),
                          binance=BinanceSyncResult(inserted=4, updated=0), classified={"rule": 5},
                          warnings=["no price for OPN on 1 day"],
                          errors=["Pluggy: item 2: HTTPStatusError: Client error '404' for url "
                                  "'https://api.pluggy.ai/items/0f8fad5b-d9cb-469f-a165-70867728950e' cpf 12345678901"])

    def open_all(self):
        for e in self.release.values():
            e.set()


# --- sync runner ----------------------------------------------------------------------------------

def test_sync_double_post_409_status_progression_and_report(api, make_client):
    gate = Gate()
    runner = SyncRunner(pipeline=gate)
    client = make_client(runner)
    idle = client.get(f"{P}/sync/status").json()
    assert idle["running"] is False and idle["step"] is None and idle["report"] is None

    r = client.post(f"{P}/sync", headers=MUTATE)
    assert r.status_code == 202 and r.json() == {"started": True}
    assert gate.reached["Bancos (Pluggy)"].wait(WAIT)
    s = client.get(f"{P}/sync/status").json()
    assert s["running"] is True and s["step"] == "Bancos (Pluggy)" and s["started_at"] and s["finished_at"] is None

    r = client.post(f"{P}/sync", headers=MUTATE)
    assert r.status_code == 409
    assert r.json() == {"error": "Uma sincronização já está em andamento.", "code": "sync_running"}

    assert client.get(f"{P}/budgets").status_code == 200  # other GETs keep answering
    gate.release["Bancos (Pluggy)"].set()
    assert gate.reached["Binance"].wait(WAIT)
    assert client.get(f"{P}/sync/status").json()["step"] == "Binance"
    gate.open_all()
    assert runner.join(WAIT)

    s = client.get(f"{P}/sync/status").json()
    assert s["running"] is False and s["finished_at"]
    rep = s["report"]
    assert rep["warnings"] == ["no price for OPN on 1 day"]
    assert rep["counts"]["pluggy"] == {"items_synced": 3, "inserted": 2, "updated": 1, "deleted": 0}
    assert rep["counts"]["binance"]["inserted"] == 4 and rep["counts"]["classified"] == {"rule": 5}
    assert len(rep["errors"]) == 1 and "Pluggy" in rep["errors"][0]
    assert "0f8fad5b" not in rep["errors"][0] and "pluggy.ai" not in rep["errors"][0]
    _no_leak(s)
    # own connection, closed afterwards
    assert gate.conns[0] is not _ws(api).conn
    with pytest.raises(sqlite3.ProgrammingError):  # "Cannot operate on a closed database"
        gate.conns[0].execute("SELECT 1")
    # a new run can start once finished
    gate2 = Gate(steps=())
    runner.pipeline = gate2
    assert client.post(f"{P}/sync", headers=MUTATE).status_code == 202
    assert runner.join(WAIT)


def test_sync_pipeline_crash_ends_in_status_not_stuck(make_client):
    def boom(conn, settings, progress):
        progress("Binance")
        raise RuntimeError("kaboom https://api.binance.com/x?signature=abc")

    runner = SyncRunner(pipeline=boom)
    client = make_client(runner)
    assert client.post(f"{P}/sync", headers=MUTATE).status_code == 202
    assert runner.join(WAIT)
    s = client.get(f"{P}/sync/status").json()
    assert s["running"] is False and s["finished_at"]
    assert s["report"]["errors"] and "RuntimeError" in s["report"]["errors"][0]
    assert "signature" not in json.dumps(s)
    assert client.post(f"{P}/sync", headers=MUTATE).status_code == 202  # not stuck
    assert runner.join(WAIT)


def test_sync_connect_failure_ends_in_status(make_client):
    runner = SyncRunner(pipeline=lambda c, s, p: SyncReport())
    make_client(runner)
    def bad_connect():
        raise OSError("disk")
    assert runner.start(bad_connect, None) is True
    assert runner.join(WAIT)
    st = runner.status()
    assert st["running"] is False and "OSError" in st["report"]["errors"][0]


def test_sync_post_needs_header(make_client):
    runner = SyncRunner(pipeline=Gate(steps=()))
    client = make_client(runner)
    assert client.post(f"{P}/sync").status_code == 403
    assert runner.status()["running"] is False and runner.status()["started_at"] is None


class BlockingClient(FakeClient):
    """Real sync.sync with a 'network' call that blocks: the API must still accept writes meanwhile."""

    def __init__(self):
        super().__init__()
        self.in_network = threading.Event()
        self.go = threading.Event()

    def iter_transactions(self, account_id, date_from=None):
        self.in_network.set()
        assert self.go.wait(WAIT)
        return super().iter_transactions(account_id, date_from)


def test_api_writes_succeed_while_real_sync_waits_on_network(api, make_client):
    fake = BlockingClient()
    _ws(api).conn.execute("PRAGMA busy_timeout = 2000")  # a held write lock fails fast instead of after 15 s

    def pipeline(conn, settings, progress):
        progress("Bancos (Pluggy)")
        result = sync(conn, fake, ["item-1"], today=TODAY)
        return SyncReport(pluggy=result, errors=result.errors)

    runner = SyncRunner(pipeline=pipeline)
    client = make_client(runner)
    assert client.post(f"{P}/sync", headers=MUTATE).status_code == 202
    assert fake.in_network.wait(WAIT)
    try:
        r = client.put(f"{P}/budgets/groceries", json={"monthly_amount": 900}, headers=MUTATE)
        assert r.status_code == 200, r.text
        r = client.post(f"{P}/manual-entries", json={"month": "2026-09", "pnl_line": "expenses",
                                                     "amount": -10, "note": "x"}, headers=MUTATE)
        assert r.status_code == 201, r.text
        assert runner.status()["running"] is True and not fake.go.is_set()  # the sync is still mid-network
    finally:
        fake.go.set()
    assert runner.join(WAIT)
    assert runner.status()["report"]["errors"] == []


def test_sync_status_items_runs_and_binance(api):
    ws = _ws(api)
    ws.conn.execute("UPDATE items SET last_updated_at = '2026-10-30T10:00:00.000Z'")
    ws.conn.execute("INSERT INTO binance_positions VALUES ('2026-10-31T09:00:00Z', 'spot', 'BTC', 0.1, 500.25)")
    ws.conn.execute("UPDATE sync_runs SET errors = ?", (json.dumps(["item 1: HTTPStatusError: url "
                                                                    "https://api.pluggy.ai/items/item-1"]),))
    ws.conn.commit()
    s = api.get(f"{P}/sync/status").json()
    item_ids = {r[0] for r in ws.conn.execute("SELECT id FROM items")}
    assert s["items"] and all(set(i) == {"name", "status", "last_updated_at"} for i in s["items"])
    assert s["items"][0]["last_updated_at"] == "2026-10-30T10:00:00.000Z"
    assert s["binance_snapshot_at"] == "2026-10-31T09:00:00Z"
    run = s["runs"][0]
    assert run["finished_at"] and run["error_count"] == 1 and "errors" not in run
    text = json.dumps(s)
    assert not any(i in text for i in item_ids)
    _no_leak(s)


# --- transfers ------------------------------------------------------------------------------------

def test_transfers_audit_labels_and_no_leak(api):
    ws = _ws(api)
    body = api.get(f"{P}/transfers").json()
    expected = agg.transfer_audit(ws.conn)
    assert len(body) == len(expected) and body
    assert [b["from_amount"] for b in body] == [e["from_amount"] for e in expected]
    assert all(b["link_label"] for b in body)
    numbers = [r[0] for r in ws.conn.execute("SELECT number_masked FROM accounts WHERE number_masked IS NOT NULL")]
    text = json.dumps(body)
    assert not any(len(n.lstrip("*")) > 4 and n in text for n in numbers)
    _no_leak(body)


def test_transfers_mask_documents_in_descriptions(api):
    ws = _ws(api)
    tx = ws.conn.execute("SELECT from_transaction_id FROM transfer_links LIMIT 1").fetchone()[0]
    ws.conn.execute("UPDATE transactions SET description = 'PIX 123.456.789-01 doc 12345678000190' WHERE id = ?", (tx,))
    ws.conn.commit()
    _no_leak(api.get(f"{P}/transfers").json())


# --- rules ----------------------------------------------------------------------------------------

def test_rules_list_hides_cnpj_and_has_labels(api):
    ws = _ws(api)
    ws.rules_path.write_text(ws.rules_path.read_text().rstrip("\n") +
                             "\n\n  - id: cnpj_rule\n    category: groceries\n    counterparty_doc: '12345678000190'\n")
    body = api.get(f"{P}/rules").json()
    rule = next(r for r in body if r["id"] == "cnpj_rule")
    assert set(rule) == {"id", "category_id", "category_label", "conditions", "priority"}
    assert rule["conditions"] == {"has_cnpj": True} and rule["category_label"] != "groceries"
    assert "cliente_exterior" in {r["id"] for r in body}
    _no_leak(body)


def test_delete_rule_reclassifies_and_404(api):
    ws = _ws(api)
    ws.rules_path.write_text(ws.rules_path.read_text().rstrip("\n") +
                             "\n\n  - id: pix_out_rule\n    category: groceries\n    party: LOJA EXEMPLO\n    direction: out\n")
    from finance.classify import classify_all, load_rules_config
    classify_all(ws.conn, ws.taxonomy, load_rules_config(ws.rules_path), ws.settings.my_cpf)
    ruled = ws.conn.execute("SELECT COUNT(*) FROM classifications WHERE rule_id = 'pix_out_rule'").fetchone()[0]
    assert ruled == 1
    assert api.delete(f"{P}/rules/pix_out_rule").status_code == 403  # header needed
    r = api.delete(f"{P}/rules/pix_out_rule", headers=MUTATE)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert "pix_out_rule" not in ws.rules_path.read_text()
    assert ws.conn.execute("SELECT COUNT(*) FROM classifications WHERE rule_id = 'pix_out_rule'").fetchone()[0] == 0
    r = api.delete(f"{P}/rules/pix_out_rule", headers=MUTATE)
    assert r.status_code == 404 and r.json()["code"] == "rule_not_found"


# --- manual entries -------------------------------------------------------------------------------

def test_manual_entries_crud(api):
    rows = api.get(f"{P}/manual-entries").json()
    assert [(r["month"], r["pnl_line"], r["amount"]) for r in rows] == [("2026-10", "income", 6420)]
    assert rows[0]["pnl_line_label"]
    r = api.post(f"{P}/manual-entries", json={"month": "2026-06", "pnl_line": "investments",
                                               "amount": -1357.91, "note": "  BTG fund purchase  "}, headers=MUTATE)
    assert r.status_code == 201
    new = r.json()
    assert new["id"] and new["note"] == "BTG fund purchase" and new["amount"] == -1357.91
    assert [e["month"] for e in api.get(f"{P}/manual-entries").json()] == ["2026-06", "2026-10"]
    assert api.delete(f"{P}/manual-entries/{new['id']}").status_code == 403
    assert api.delete(f"{P}/manual-entries/{new['id']}", headers=MUTATE).status_code == 204
    r = api.delete(f"{P}/manual-entries/{new['id']}", headers=MUTATE)
    assert r.status_code == 404 and r.json()["code"] == "manual_entry_not_found"


@pytest.mark.parametrize("patch,code", [
    ({"month": "2026-13"}, "invalid_month"),
    ({"month": "2026-1"}, "invalid_month"),
    ({"pnl_line": "net_income"}, "invalid_pnl_line"),
    ({"pnl_line": "excluded"}, "invalid_pnl_line"),
    ({"amount": 0}, "invalid_amount"),
    ({"note": "   "}, "note_required"),
    ({"note": "x" * 501}, "note_too_long"),
])
def test_manual_entry_validation(api, patch, code):
    body = {"month": "2026-06", "pnl_line": "expenses", "amount": -10.0, "note": "ok", **patch}
    r = api.post(f"{P}/manual-entries", json=body, headers=MUTATE)
    assert r.status_code == 422 and r.json()["code"] == code and r.json()["error"]


def test_manual_entry_infinite_and_missing_fields(api):
    r = api.post(f"{P}/manual-entries", content='{"month": "2026-06", "pnl_line": "expenses", "amount": Infinity, '
                 '"note": "x"}', headers={**MUTATE, "Content-Type": "application/json"})
    assert r.status_code == 422
    r = api.post(f"{P}/manual-entries", json={"month": "2026-06"}, headers=MUTATE)
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    assert api.post(f"{P}/manual-entries", json={"month": "2026-06", "pnl_line": "expenses", "amount": 1,
                                                  "note": "x"}).status_code == 403


def test_sync_refuses_in_memory_db_and_never_falls_back(api, monkeypatch, tmp_path):
    """No file path on the request DB: never connect(None) (that would open FINANCE_DB / data/finance.db)."""
    import sqlite3

    from finance.api import Workspace
    from finance.api.routes import settings as settings_route

    calls = []
    monkeypatch.setattr(settings_route, "connect", lambda *a, **k: calls.append(a) or sqlite3.connect(":memory:"))
    monkeypatch.setenv("FINANCE_DB", str(tmp_path / "must-not-open.db"))
    ws = _ws(api)
    mem = sqlite3.connect(":memory:", check_same_thread=False)
    mem.row_factory = sqlite3.Row
    mem_ws = Workspace(conn=mem, taxonomy=ws.taxonomy, rules_path=ws.rules_path, settings=ws.settings)
    runner = SyncRunner(pipeline=lambda c, s, p: SyncReport())
    with TestClient(create_app(workspace_factory=lambda: mem_ws, sync_runner=runner),
                    base_url="http://localhost") as client:
        r = client.post(f"{P}/sync", headers=MUTATE)
        assert runner.join(WAIT)
    assert r.status_code == 500
    assert r.json()["code"] == "sync_unavailable" and r.json()["error"]
    assert runner.status()["started_at"] is None
    assert calls == []
