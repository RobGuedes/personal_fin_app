import re

import pytest

from finance import aggregate as agg
from finance import networth
from test_api_panorama import fixed_now  # noqa: F401
from test_api_summary import _rows

P = "/api/v1"
DOCS = re.compile(r"(?<!\d)(\d{11}|\d{14}|\d{3}\.\d{3}\.\d{3}-\d{2}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})(?!\d)")


def _seed(ws):
    c = ws.conn
    item = c.execute("SELECT id FROM items LIMIT 1").fetchone()[0]
    c.execute("UPDATE items SET last_updated_at = '2026-10-30T10:00:00.000Z' WHERE id = ?", (item,))
    c.execute("INSERT INTO accounts (id, item_id, type, name, number_masked, owner_doc, balance, raw_json) "
              "VALUES ('binance', ?, 'BANK', 'Binance', NULL, '12345678901', 999, '{\"cpf\": \"12345678901\"}')", (item,))
    c.execute("INSERT INTO investments (id, item_id, name, type, subtype, balance, currency, raw_json, updated_at) "
              "VALUES ('p1', ?, 'CDB BANCO 12345678000190 ISIN BRABCDE12345 numero 987654321', 'FIXED_INCOME', 'CDB', "
              "1000.5, 'BRL', '{\"raw_json\": 1, \"cnpj\": \"12345678000190\"}', '2026-10-31T08:00:00Z')", (item,))
    c.execute("INSERT INTO binance_positions VALUES ('2026-10-31T09:00:00Z', 'spot', 'BTC', 0.1, 500.25)")
    c.execute("INSERT INTO binance_positions VALUES ('2026-10-31T09:00:00Z', 'earn_flexible', 'USDT', 10, 55.0)")
    c.commit()


def test_networth_shape_and_sums(api):
    ws, _ = _rows(api)
    _seed(ws)
    body = api.get(f"{P}/networth").json()
    totals = networth.group_totals(ws.conn)
    assert [g["grp"] for g in body["groups"]] == ["investments", "accounts", "crypto", "cards"]
    assert [g["label"] for g in body["groups"]] == ["Investimentos", "Contas", "Cripto", "Cartões"]
    for g in body["groups"]:
        assert g["value"] == pytest.approx(totals[g["grp"]], abs=0.005)
        assert sum(a["value"] for a in g["accounts"]) == pytest.approx(g["value"], abs=0.005)
    assert body["total"] == pytest.approx(sum(totals.values()), abs=0.005)
    by = {g["grp"]: g for g in body["groups"]}
    labels = agg.account_labels(ws.conn)
    bank = ws.conn.execute("SELECT id FROM accounts WHERE type='BANK' AND id != 'binance'").fetchall()
    assert {a["label"] for a in by["accounts"]["accounts"]} == {labels[r[0]] for r in bank}
    assert all(a["value"] <= 0 for a in by["cards"]["accounts"]) and by["cards"]["accounts"]
    assert {a["label"] for a in by["crypto"]["accounts"]} == {"BTC", "USDT"}
    inv = by["investments"]["accounts"]
    assert len(inv) == 1 and len(inv[0]["label"]) <= 80 and not re.search(r"\d{6,}", inv[0]["label"])
    assert inv[0]["updated_at"] == "2026-10-31T08:00:00Z"
    assert body["as_of"] == "2026-10-31T09:00:00Z"


def test_networth_empty_db_as_of_null(api):
    ws, _ = _rows(api)
    ws.conn.execute("UPDATE items SET last_updated_at = NULL")
    ws.conn.commit()
    body = api.get(f"{P}/networth").json()
    assert body["as_of"] is None
    assert [g["grp"] for g in body["groups"]][0] == "investments"


def test_history(api):
    ws, _ = _rows(api)
    networth.snapshot(ws.conn, "2026-10-30", {"accounts", "cards"}, {"accounts": 10.0, "cards": -3.0})
    assert api.get(f"{P}/networth/history").json() == networth.history(ws.conn)


def test_contributions_parity_and_period(api):
    ws, rows = _rows(api)
    body = api.get(f"{P}/networth/contributions", params={"period": "year:2026"}).json()
    months = body["months"]
    table = agg.with_totals(agg.pnl(rows, agg.manual_entries(ws.conn), ws.taxonomy, months), months)
    line7 = next(r for r in table if r["key"] == "investments" and r["level"] == 0)
    assert len(months) == 10
    for m in months:
        assert body["values"][m] == pytest.approx(-line7[m], abs=0.005)
    assert body["total"] == pytest.approx(-line7["total"], abs=0.005)
    r = api.get(f"{P}/networth/contributions", params={"period": "bogus"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_period"


def test_accounts(api):
    ws, _ = _rows(api)
    _seed(ws)
    body = api.get(f"{P}/accounts").json()
    labels = agg.account_labels(ws.conn)
    assert {a["id"] for a in body} == set(labels)
    assert all(set(a) == {"id", "label", "type", "institution"} for a in body)
    assert {a["id"]: a["label"] for a in body} == labels


def test_no_leaks(api):
    ws, _ = _rows(api)
    _seed(ws)
    ws.conn.execute("UPDATE accounts SET owner_doc = '12345678901'")
    ws.conn.commit()
    for path in ("/networth", "/networth/history", "/networth/contributions", "/accounts"):
        text = api.get(P + path).text
        assert "raw_json" not in text and not DOCS.search(text), path


def test_investment_institution_suffix_and_masking(api):
    ws, _ = _rows(api)
    c = ws.conn
    for i in ("itemA", "itemB", "itemC"):
        c.execute("INSERT INTO items (id, raw_json) VALUES (?, '{}')", (i,))
    acc = "INSERT INTO accounts (id, item_id, type, name, balance, raw_json) VALUES (?,?,?,?,0,'{}')"
    c.execute(acc, ("a0", "itemA", "CREDIT", "CARTAO EXEMPLO VISA"))
    c.execute(acc, ("a1", "itemA", "BANK", "XP"))
    c.execute(acc, ("a2", "itemA", "BANK", "xp"))
    c.execute(acc, ("b1", "itemB", "BANK", "itau"))
    c.execute(acc, ("b2", "itemB", "BANK", "BTG"))
    c.execute(acc, ("c1", "itemC", "CREDIT", "CARTAO"))
    pos = "INSERT INTO investments (id, item_id, name, balance, currency, raw_json, updated_at) VALUES (?,?,?,?,'BRL','{}','2026-10-31T00:00:00Z')"
    c.execute(pos, ("pa", "itemA", "Fundo A 12.345.678/0001-90", 1.0))
    c.execute(pos, ("pb", "itemB", "Fundo B 123.456.789-01", 2.0))
    c.execute(pos, ("pc", "itemC", "Fundo C", 3.0))
    c.commit()
    inv = {a["label"] for a in next(g for g in api.get(f"{P}/networth").json()["groups"] if g["grp"] == "investments")["accounts"]}
    assert "Fundo A ••• · XP" in inv
    assert "Fundo B •••" in inv and "Fundo C" in inv
