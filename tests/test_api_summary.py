import re
from pathlib import Path

import pytest

from finance import aggregate as agg
from finance.api.routes import summary as summary_routes
from finance.classify import load_taxonomy
from samples import CATEGORIES_FIXTURE


def _rows(client):
    ws = client.app.dependency_overrides[next(iter(client.app.dependency_overrides))]()
    return ws, agg.ledger(ws.conn, ws.taxonomy)


def test_month_summary_matches_pnl(api):
    ws, rows = _rows(api)
    expected = agg.line_totals(agg.pnl(rows, agg.manual_entries(ws.conn), ws.taxonomy, ["2026-10"]), ["2026-10"])
    body = api.get("/api/v1/summary/month", params={"month": "2026-10"}).json()
    assert body["month"] == "2026-10" and not body["is_current"]
    assert body["day"] == body["days_in_month"] == 31
    for k, v in body["totals"].items():
        assert v == pytest.approx(expected[k], abs=0.005)
    assert body["totals"]["income"] != 0
    assert body["renda_split"]["renda"] == pytest.approx(expected["income"], abs=0.005)
    assert isinstance(body["categories"], list)


def test_review_count_matches_queue(api):
    ws, rows = _rows(api)
    queue = agg.review_queue(rows, ws.taxonomy.settings["review_confidence_below"])
    body = api.get("/api/v1/summary/month", params={"month": "2026-10"}).json()
    assert body["review_count"] == len({r["id"] for r in queue}) > 0


def test_trend_matches_pnl(api):
    ws, rows = _rows(api)
    months = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    table = agg.pnl(rows, agg.manual_entries(ws.conn), ws.taxonomy, months)
    body = api.get("/api/v1/trend", params={"months": 6, "to": "2026-10"}).json()
    assert [p["month"] for p in body] == months
    for p in body:
        t = agg.line_totals(table, [p["month"]])
        assert p["income"] == pytest.approx(t["income"], abs=0.005)
        assert p["spending"] == pytest.approx(-(t["tax_provision"] + t["commissions"] + t["expenses"]),
                                              abs=0.005)


def test_taxonomy_has_every_category(api, november):
    body = api.get("/api/v1/taxonomy").json()
    tx = load_taxonomy(CATEGORIES_FIXTURE)
    assert {c["id"] for c in body["categories"]} == set(tx.categories)
    assert {l["id"] for l in body["lines"]} == set(tx.lines)
    assert all(c["icon"] for c in body["categories"])
    slots = [c["color_slot"] for c in body["categories"] if c["color_slot"] is not None]
    assert slots and all(0 <= s < 8 for s in slots)


def test_summary_never_leaks_documents(api):
    for url in ("/api/v1/summary/month?month=2026-10", "/api/v1/trend?months=6&to=2026-10", "/api/v1/taxonomy"):
        assert not re.search(r"(?<!\d)(\d{11}|\d{14})(?!\d)", api.get(url).text)


def test_bad_month_rejected(api):
    assert api.get("/api/v1/summary/month?month=2026-13").status_code == 422


def _spending_expected(t):
    return -(t["commissions"] + t["expenses"])


def test_spending_matches_pnl_and_categories(api):
    ws, rows = _rows(api)
    victim = next(r for r in rows if r["month"] == "2026-10" and r["amount"] < 0 and r["line"] == "expenses"
                  and r["source"] != "manual")
    ws.conn.execute("DELETE FROM classifications WHERE transaction_id = ?", (victim["id"],))
    ws.conn.commit()
    ws, rows = _rows(api)
    assert any(r["month"] == "2026-10" and r["category_id"] == "uncategorized" and r["amount"] < 0 for r in rows)
    body = api.get("/api/v1/summary/month", params={"month": "2026-10"}).json()
    t = agg.line_totals(agg.pnl(rows, agg.manual_entries(ws.conn), ws.taxonomy, ["2026-10"]), ["2026-10"])
    manual = sum(e["amount"] for e in agg.manual_entries(ws.conn) if e["month"] == "2026-10"
                 and e["pnl_line"] in ("commissions", "expenses"))
    assert body["spending"]["spent"] == pytest.approx(_spending_expected(t) + manual, abs=0.005)
    assert body["spending"]["spent"] == pytest.approx(sum(c["spent"] for c in body["categories"]), abs=0.005)
    assert "uncategorized" in {c["category_id"] for c in body["categories"]}


def test_manual_expense_changes_totals_not_spending(api):
    before = api.get("/api/v1/summary/month", params={"month": "2026-10"}).json()
    ws, _ = _rows(api)
    ws.conn.execute("INSERT INTO manual_entries (month, pnl_line, amount, note) VALUES ('2026-10', 'expenses', -500, 'x')")
    ws.conn.commit()
    after = api.get("/api/v1/summary/month", params={"month": "2026-10"}).json()
    assert after["totals"]["expenses"] == pytest.approx(before["totals"]["expenses"] - 500, abs=0.005)
    assert after["spending"] == before["spending"]


def test_current_month_uses_today(api, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from finance.api.routes import summary
    monkeypatch.setattr(summary, "local_now", lambda: datetime(2026, 10, 15, 12, tzinfo=ZoneInfo("America/Sao_Paulo")))
    body = api.get("/api/v1/summary/month").json()
    assert body["month"] == "2026-10" and body["is_current"] and body["day"] == 15 and body["days_in_month"] == 31
    full = api.get("/api/v1/summary/month", params={"month": "2026-09"}).json()
    assert not full["is_current"] and full["day"] == 30


def test_review_count_equals_inbox_including_future_month(api, monkeypatch):
    import finance.llm as llm
    monkeypatch.setattr(llm, "HELPER_BIN", Path("/nonexistent/helper"))
    ws, _ = _rows(api)
    # tx-inst-10 is a PENDING future installment (month 2027-04): it belongs to the queue like any other row.
    ws.conn.execute("UPDATE classifications SET confidence = 0.4 WHERE transaction_id = 'tx-inst-10'")
    ws.conn.commit()
    inbox = api.get("/api/v1/review").json()
    assert "tx-inst-10" in {i["id"] for i in inbox}
    for month in ("2026-10", None):
        body = api.get("/api/v1/summary/month", params={"month": month} if month else {}).json()
        assert body["review_count"] == len(inbox)


def test_income_sources_shape_order_labels(api):
    ws, rows = _rows(api)
    body = api.get("/api/v1/summary/month", params={"month": "2026-10"}).json()
    sources = body["income_sources"]
    assert sources and all(set(s) == {"key", "label", "amount"} for s in sources)
    amounts = [s["amount"] for s in sources]
    assert all(a > 0 for a in amounts) and amounts == sorted(amounts, reverse=True)
    labels = {s["key"]: s["label"] for s in sources}
    assert labels["manual:income"] == "Lançamentos manuais"
    for key, label in labels.items():
        if key in ws.taxonomy.categories:
            attrs = ws.taxonomy.categories[key]
            assert label == (attrs.get("label_pt") or attrs.get("label", key))
            assert ws.taxonomy.categories[key]["line"] == "income"


def test_income_sources_sum_to_income(api):
    """Parity with totals.income. breakdown() drops components that net <= 0 (refunds bigger than the
    income in a category), so equality only holds when every component is positive; the fixture month is."""
    ws, rows = _rows(api)
    table = agg.pnl(rows, agg.manual_entries(ws.conn), ws.taxonomy, ["2026-10"])
    components = [r["2026-10"] for r in table if r["level"] == 1 and r["line"] == "income" and r["2026-10"]]
    assert components and all(v > 0 for v in components)
    body = api.get("/api/v1/summary/month", params={"month": "2026-10"}).json()
    assert sum(s["amount"] for s in body["income_sources"]) == pytest.approx(body["totals"]["income"], abs=0.01)


def test_income_sources_uncategorized_label(api):
    ws, rows = _rows(api)
    victim = next(r for r in rows if r["month"] == "2026-10" and r["amount"] > 0 and r["line"] == "income"
                  and r["source"] != "manual")
    ws.conn.execute("DELETE FROM classifications WHERE transaction_id = ?", (victim["id"],))
    ws.conn.commit()
    body = api.get("/api/v1/summary/month", params={"month": "2026-10"}).json()
    labels = {s["key"]: s["label"] for s in body["income_sources"]}
    assert labels["uncategorized:income"] == "Sem categoria"
    assert sum(s["amount"] for s in body["income_sources"]) == pytest.approx(body["totals"]["income"], abs=0.01)


WINDOW = [f"2025-{m:02d}" for m in range(11, 13)] + [f"2026-{m:02d}" for m in range(1, 11)]  # Nov/25–Oct/26


@pytest.fixture
def november(monkeypatch):
    """Pin today to 2026-11-15: slots rank Nov/2025–Oct/2026, the fixture's data months."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from finance.api.routes import summary
    monkeypatch.setattr(summary, "local_now", lambda: datetime(2026, 11, 15, 12, tzinfo=ZoneInfo("America/Sao_Paulo")))


def _outflow_ranking(ws, rows, months=WINDOW):
    table = agg.pnl(rows, agg.manual_entries(ws.conn), ws.taxonomy, months)
    items = [i for line in ("commissions", "expenses") for i in agg.breakdown(table, line, months)
             if i[0] in ws.taxonomy.categories]
    return [k for k, _l, _v in sorted(items, key=lambda i: -i[2])]


def _slots(api):
    return {c["id"]: c["color_slot"] for c in api.get("/api/v1/taxonomy").json()["categories"]}


def test_outflow_slots_rank_commissions_and_expenses_together(api, november):
    ws, rows = _rows(api)
    ranked = _outflow_ranking(ws, rows)
    slots = _slots(api)
    for i, key in enumerate(ranked[:8]):
        assert slots[key] == i
    for key in ranked[8:]:
        assert slots[key] is None


def test_donations_get_a_slot_when_among_top_outflows(api, november):
    ws, rows = _rows(api)
    assert "donations" in _outflow_ranking(ws, rows)[:8]  # the fixture's charity charge is among its largest outflows
    assert _slots(api)["donations"] is not None


def test_commissions_get_a_slot_when_among_top_outflows(api, november):
    ws, rows = _rows(api)
    victim = next(r for r in rows if r["category_id"] == "shopping" and r["amount"] < 0 and r["source"] != "manual")
    ws.conn.execute("UPDATE classifications SET category_id = 'commissions' WHERE transaction_id = ?", (victim["id"],))
    ws.conn.commit()
    ws, rows = _rows(api)
    assert "commissions" in _outflow_ranking(ws, rows)[:8]
    assert _slots(api)["commissions"] is not None


def test_slots_rank_only_the_last_12_complete_months(api, monkeypatch):
    """Today in Oct/2026: the window is Oct/2025–Sep/2026, so Oct/2026 spending (current month) does not count."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from finance.api.routes import summary
    monkeypatch.setattr(summary, "local_now", lambda: datetime(2026, 10, 15, 12, tzinfo=ZoneInfo("America/Sao_Paulo")))
    ws, rows = _rows(api)
    oct_only = {r["category_id"] for r in rows if r["month"] == "2026-10"} - {r["category_id"] for r in rows
                                                                             if r["month"] != "2026-10"}
    oct_only &= set(ws.taxonomy.categories)
    assert oct_only  # the fixture has categories used only in Oct/2026
    slots = _slots(api)
    assert all(slots[c] is None for c in oct_only)
    window = [f"2025-{m:02d}" for m in range(10, 13)] + [f"2026-{m:02d}" for m in range(1, 10)]
    for i, key in enumerate(_outflow_ranking(ws, rows, window)[:8]):
        assert slots[key] == i


def test_income_link_lists_uncategorized_inflows(api):
    """The income card links to /transactions?month=&line=income: uncategorized inflows must be listed, and the
    list sums to the card's total minus manual entries (which are not ledger rows; the card notes them)."""
    ws, rows = _rows(api)
    victim = next(r for r in rows if r["month"] == "2026-10" and r["amount"] > 0 and r["line"] == "income"
                  and r["source"] != "manual")
    ws.conn.execute("DELETE FROM classifications WHERE transaction_id = ?", (victim["id"],))
    ws.conn.commit()
    listed = api.get("/api/v1/transactions", params={"month": "2026-10", "line": "income", "limit": 500}).json()
    assert victim["id"] in {i["id"] for i in listed["items"]}
    assert listed["next_cursor"] is None
    body = api.get("/api/v1/summary/month", params={"month": "2026-10"}).json()
    manual = sum(s["amount"] for s in body["income_sources"] if s["key"].startswith("manual:"))
    assert manual > 0
    assert sum(i["amount"] for i in listed["items"]) == pytest.approx(body["totals"]["income"] - manual, abs=0.01)


def test_income_slots_only_real_categories(api, november):
    ws, rows = _rows(api)
    inflow = next(r for r in rows if r["month"] == "2026-10" and r["amount"] > 0 and r["source"] != "manual")
    ws.conn.execute("INSERT OR REPLACE INTO classifications (transaction_id, category_id, source, classified_at) "
                    "VALUES (?, 'dividends', 'manual', '2026-10-31')", (inflow["id"],))
    ws.conn.execute("INSERT INTO manual_entries (month, pnl_line, amount, note) VALUES ('2026-10', 'income', 1e6, 'big')")
    ws.conn.commit()
    slots = _slots(api)
    assert slots["dividends"] == 0  # the larger manual:income entry must not take slot 0
    assert {k for k in slots if slots[k] is not None} <= set(ws.taxonomy.categories)
    income = sorted(s for k, s in slots.items() if s is not None and ws.taxonomy.categories[k]["line"] == "income")
    assert income == list(range(len(income)))  # manual:income must not take a slot (would leave a hole)


def test_taxonomy_first_month_is_first_ledger_month(api):
    ws, rows = _rows(api)
    expected = summary_routes.all_months(rows)[0]
    body = api.get("/api/v1/taxonomy").json()
    assert body["first_month"] == expected
    assert re.fullmatch(r"\d{4}-\d{2}", body["first_month"])
