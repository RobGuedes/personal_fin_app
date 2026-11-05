import json

import pytest

from finance import networth
from finance.db import connect


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "n.db")
    for i in ("i1", "i2"):
        c.execute("INSERT INTO items (id, raw_json) VALUES (?, '{}')", (i,))
    c.commit()
    return c


def _acct(conn, id, typ, balance, item="i1"):
    conn.execute("INSERT INTO accounts (id, item_id, type, balance, raw_json) VALUES (?,?,?,?, '{}')",
                 (id, item, typ, balance))


def _pos(id, balance=100.0, status="ACTIVE", currency="BRL", **kw):
    return {"id": id, "name": f"n-{id}", "type": "FIXED_INCOME", "subtype": "CDB", "balance": balance,
            "currencyCode": currency, "date": "2026-10-30T00:00:00.000Z", "status": status,
            "owner": "SECRET", **kw}


class FakeClient:
    def __init__(self, by_item):
        self.by_item = by_item

    def list_investments(self, item_id):
        v = self.by_item[item_id]
        if isinstance(v, Exception):
            raise v
        return v


def test_sync_investments_stores_active_only_and_deletes_gone(conn):
    n = networth.sync_investments(conn, FakeClient({"i1": [_pos("a", 10), _pos("b", 5, "TOTAL_WITHDRAWAL")],
                                                    "i2": [_pos("c", 7)]}), ["i1", "i2"])
    assert n == 2
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM investments")}
    assert set(rows) == {"a", "c"} and rows["a"]["balance"] == 10 and rows["a"]["currency"] == "BRL"
    assert rows["a"]["balance_date"] == "2026-10-30T00:00:00.000Z"
    assert json.loads(rows["a"]["raw_json"])["id"] == "a"
    # next run: a closed, i2 not touched
    networth.sync_investments(conn, FakeClient({"i1": [_pos("a", 10, "TOTAL_WITHDRAWAL")]}), ["i1"])
    assert {r[0] for r in conn.execute("SELECT id FROM investments")} == {"c"}


def test_sync_investments_failure_keeps_stored_positions(conn):
    networth.sync_investments(conn, FakeClient({"i1": [_pos("a")]}), ["i1"])
    with pytest.raises(RuntimeError):
        networth.sync_investments(conn, FakeClient({"i1": RuntimeError("x")}), ["i1"])
    assert {r[0] for r in conn.execute("SELECT id FROM investments")} == {"a"}


def test_group_totals(conn, caplog):
    _acct(conn, "c1", "BANK", 1000.0)
    _acct(conn, "c2", "BANK", -50.0)
    _acct(conn, "cc", "CREDIT", 300.0)
    _acct(conn, "cc2", "CREDIT", 200.0, "i2")
    _acct(conn, "binance", "BANK", 99999.0)
    networth.sync_investments(conn, FakeClient({"i1": [_pos("a", 400), _pos("u", 5, currency="USD")]}), ["i1"])
    conn.execute("INSERT INTO binance_positions VALUES ('2026-11-01T10:00:00', 'spot', 'BTC', 1, 700)")
    conn.commit()
    with caplog.at_level("WARNING"):
        t = networth.group_totals(conn)
    assert t == {"accounts": 950.0, "investments": 400.0, "crypto": 700.0, "cards": -500.0}
    assert "USD" in caplog.text


def test_group_totals_without_binance(conn):
    assert networth.group_totals(conn) == {"accounts": 0, "investments": 0, "crypto": 0, "cards": 0}


def test_snapshot_only_writes_succeeded_groups(conn):
    networth.snapshot(conn, "2026-11-01", {"accounts", "crypto"}, {"accounts": 10, "investments": 20,
                                                                    "crypto": 30, "cards": -5})
    assert {r[0] for r in conn.execute("SELECT grp FROM net_worth_snapshots")} == {"accounts", "crypto"}
    networth.snapshot(conn, "2026-11-02", {"accounts", "investments", "cards"},
                      {"accounts": 11, "investments": 21, "crypto": 0.0, "cards": -6})
    rows = conn.execute("SELECT grp FROM net_worth_snapshots WHERE date='2026-11-02'").fetchall()
    assert {r[0] for r in rows} == {"accounts", "investments", "cards"}
    # upsert
    networth.snapshot(conn, "2026-11-02", {"accounts"}, {"accounts": 12})
    assert conn.execute("SELECT value FROM net_worth_snapshots WHERE date='2026-11-02' AND grp='accounts'"
                        ).fetchone()[0] == 12
    h = networth.history(conn)
    assert h[1]["crypto"] == 30  # Binance missing on day 2: carried forward, not 0


def test_history_total(conn, tmp_path):
    s = networth.snapshot
    s(conn, "2026-11-01", {"investments"}, {"investments": 100})
    s(conn, "2026-11-02", {"accounts", "investments", "cards"}, {"accounts": 50, "investments": 110, "cards": -20})
    s(conn, "2026-11-03", {"accounts", "investments", "cards", "crypto"},
      {"accounts": 60, "investments": 120, "cards": -10, "crypto": 5})
    h = networth.history(conn)
    assert [r["date"] for r in h] == ["2026-11-01", "2026-11-02", "2026-11-03"]
    # groups with no value yet are 0 in total
    assert h[0] == {"date": "2026-11-01", "accounts": 0, "investments": 100, "crypto": 0, "cards": 0, "total": 100}
    assert h[1]["total"] == 140 and h[2]["total"] == 175
    assert networth.history(connect(tmp_path / "e.db")) == []
