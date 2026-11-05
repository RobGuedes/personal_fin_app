import shutil

import pytest
import yaml

from finance import aggregate as agg
from finance.classify import append_rule, load_taxonomy, suggest_rule
from finance.fmt import brl
from samples import CATEGORIES_FIXTURE, RULES_FIXTURE

TAX = load_taxonomy(CATEGORIES_FIXTURE)


def r(id, month, amount, category, line=None, source="rule", **kw):
    return {"id": id, "month": month, "amount": amount, "category_id": category,
            "line": line or TAX.line_of(category) or ("expenses" if amount < 0 else "income"),
            "source": source, "account_id": "a", "payment_method": "pix", **kw}


def test_brl():
    assert brl(1234.5) == "R$ 1.234,50"
    assert brl(-1234567.891) == "-R$ 1.234.567,89"
    assert brl(0) == "R$ 0,00" and brl(-0.001) == "R$ 0,00"


def test_pnl_lines_net_income_and_provision():
    months = ["2026-09", "2026-10"]
    rows = [
        r("nf", "2026-10", 10000.0, "services_nf"),
        r("div", "2026-10", 20000.0, "dividends"),
        r("comm", "2026-10", -2500.0, "commissions"),
        r("gift", "2026-10", -4500.0, "donations"),
        r("food", "2026-10", -1000.0, "groceries"),
        r("refund", "2026-10", 100.0, "groceries"),
        r("unk", "2026-10", -50.0, "uncategorized", line="expenses"),
        r("bill", "2026-10", -3210.0, "card_bill_payment"),
        r("inv", "2026-09", -5000.0, "investment_contribution"),
    ]
    entries = [{"month": "2026-10", "pnl_line": "income", "amount": 6420.0},
               {"month": "2025-01", "pnl_line": "income", "amount": 999.0}]  # outside the range
    table = {x["key"]: x for x in agg.with_totals(agg.pnl(rows, entries, TAX, months), months)}
    oct_ = "2026-10"
    assert table["income"][oct_] == 10000 + 20000 + 6420
    assert table["manual:income"][oct_] == 6420
    assert table["tax_provision"][oct_] == -600.0              # 6% of NF income only
    assert table["commissions"][oct_] == -2500.0
    assert table["donations"][oct_] == -4500.0
    assert table["expenses"][oct_] == -4500 - 1000 + 100 - 50  # refund nets, uncategorized counts
    assert table["net_income"][oct_] == 36420 - 600 - 2500 - 5450
    assert table["investments"]["2026-09"] == -5000.0
    assert "card_bill_payment" not in table                   # excluded line is not in the P&L
    assert table["investments"]["total"] == -5000.0 and table["investments"]["average"] == -2500.0
    order = [x["key"] for x in agg.pnl(rows, entries, TAX, months) if x["level"] == 0]
    assert order == ["income", "tax_provision", "commissions", "expenses", "net_income", "investments"]


def test_channels_and_top_counterparties_ignore_excluded_and_investments():
    rows = [r("a", "2026-10", -100.0, "groceries", counterparty_name="MERCADO", merchant_name=None, description="x"),
            r("b", "2026-10", -50.0, "groceries", counterparty_name="mercado ", merchant_name=None, description="y"),
            r("c", "2026-10", -3210.0, "card_bill_payment", counterparty_name=None, merchant_name=None, description="z"),
            r("d", "2026-10", -900.0, "investment_contribution", counterparty_name=None, merchant_name=None, description="w")]
    assert agg.top_counterparties(rows) == [("MERCADO", 150.0, 2)]
    assert agg.outflows_by_channel(rows) == {"pix": {"2026-10": 150.0}}


def test_suggest_rule_prefers_cnpj_and_never_uses_cpf():
    company = suggest_rule({"amount": -50.0, "counterparty_name": "LOJA X LTDA", "merchant_name": None,
                            "counterparty_doc": "12345678000190", "description": "Pagamento"}, "shopping")
    assert company["counterparty_doc"] == "12345678000190" and company["direction"] == "out"
    person = suggest_rule({"amount": -1500.0, "counterparty_name": None, "merchant_name": None,
                           "counterparty_doc": "11122233344", "description": "Pix enviado FULANO DE TAL"}, "kids")
    assert "counterparty_doc" not in person and person["party"] == "FULANO DE TAL"
    assert person["id"] == "fulano_de_tal_out"
    school = suggest_rule({"amount": -1980.45, "counterparty_name": None, "merchant_name": None,
                           "counterparty_doc": None, "description": "ESCOLA EXEMPLO CENTRO01/11"}, "education")
    assert school["party"] == "ESCOLA EXEMPLO CENTRO"


@pytest.fixture
def rules_copy(tmp_path):
    path = tmp_path / "rules.yaml"
    shutil.copy(RULES_FIXTURE, path)
    return path


def test_append_rule_keeps_comments_and_makes_id_unique(rules_copy):
    before = rules_copy.read_text()
    new_id = append_rule({"id": "cliente_exterior", "party": "FOO", "direction": "out", "category": "gifts",
                          "comment": "test"}, TAX, rules_copy)
    assert new_id == "cliente_exterior_2"
    text = rules_copy.read_text()
    assert text.startswith(before.rstrip("\n")) and "# test" in text
    rules = yaml.safe_load(text)["rules"]
    assert rules[-1] == {"id": "cliente_exterior_2", "party": "FOO", "direction": "out", "category": "gifts"}


def test_append_rule_with_unknown_category_restores_file(rules_copy):
    before = rules_copy.read_text()
    with pytest.raises(ValueError):
        append_rule({"id": "x", "party": "FOO", "category": "nope"}, TAX, rules_copy)
    assert rules_copy.read_text() == before


def test_breakdown_and_stable_slots():
    months = ["2026-09", "2026-10"]
    rows = [r("a", "2026-10", -300.0, "groceries"), r("b", "2026-09", -100.0, "groceries"),
            r("c", "2026-10", -50.0, "travel"), r("d", "2026-10", 80.0, "shopping"),  # refunds > spend: dropped
            r("e", "2026-10", -20.0, "health"), r("i", "2026-10", 1000.0, "dividends")]
    table = agg.pnl(rows, [], TAX, months)
    exp = agg.breakdown(table, "expenses", months)
    assert [(k, v) for k, _, v in exp] == [("groceries", 400.0), ("travel", 50.0), ("health", 20.0)]
    assert agg.breakdown(table, "income", months)[0][0] == "dividends"
    assert agg.stable_slots(exp, 2) == {"groceries": 0, "travel": 1}
    totals = agg.line_totals(table, ["2026-10"])
    assert totals["expenses"] == -290.0 and totals["income"] == 1000.0


def test_account_labels_are_unique():
    from finance.db import connect
    conn = connect(":memory:")
    conn.execute("INSERT INTO items (id, raw_json) VALUES ('i', '{}')")
    for acc_id, name, number, subtype in [("a1", "XP", "0003", "CHECKING_ACCOUNT"), ("a2", "XP", "0003", "CHECKING_ACCOUNT"),
                                          ("b1", "itau", "0004", "CHECKING_ACCOUNT"), ("b2", "itau", "0004", "SAVINGS_ACCOUNT"),
                                          ("c1", "BTG", "0001", "CHECKING_ACCOUNT")]:
        conn.execute("INSERT INTO accounts (id, item_id, type, subtype, name, number_masked, raw_json) "
                     "VALUES (?, 'i', 'BANK', ?, ?, ?, '{}')", (acc_id, subtype, name, number))
    labels = agg.account_labels(conn)
    assert labels == {"a1": "XP 0003 (checking 1)", "a2": "XP 0003 (checking 2)", "b1": "itau 0004 (checking)",
                      "b2": "itau 0004 (savings)", "c1": "BTG 0001"}


def test_binance_holdings_latest_snapshot(tmp_path):
    from finance.db import connect
    conn = connect(tmp_path / "h.db")
    assert agg.binance_holdings(conn) is None
    rows = [("2026-10-31T03:00:00+00:00", "spot", "BTC", 1.0, 100.0),
            ("2026-11-01T03:00:00+00:00", "spot", "BTC", 1.0, 300.0),
            ("2026-11-01T03:00:00+00:00", "earn_flexible", "BTC", 1.0, 50.0),
            ("2026-11-01T03:00:00+00:00", "spot", "ETH", 1.0, 400.0)]
    conn.executemany("INSERT INTO binance_positions VALUES (?,?,?,?,?)", rows)
    h = agg.binance_holdings(conn)
    assert h["snapshot_at"] == "2026-11-01T03:00:00+00:00"
    assert h["total_brl"] == 750.0
    assert h["by_asset"] == [("ETH", 400.0), ("BTC", 350.0)]
