import pytest

from finance import aggregate as agg
from finance import insights
from finance.api.routes import summary
from finance.classify import load_taxonomy
from samples import CATEGORIES_FIXTURE
from test_api_summary import _rows

P = "/api/v1"


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    monkeypatch.setattr(summary, "local_now", lambda: datetime(2026, 10, 31, 12, tzinfo=ZoneInfo("America/Sao_Paulo")))


def _months(period="last12"):
    all_m = []
    return insights.period_months(period, "2026-10", all_m)


def test_pnl_parity(api):
    ws, rows = _rows(api)
    months = _months()
    expected = agg.with_totals(agg.pnl(rows, agg.manual_entries(ws.conn), ws.taxonomy, months), months)
    body = api.get(f"{P}/pnl", params={"period": "last12"}).json()
    assert body["months"] == months
    assert [r["key"] for r in body["rows"]] == [r["key"] for r in expected]
    for got, exp in zip(body["rows"], expected, strict=True):
        assert got["level"] == exp["level"] and got["line"] == exp["line"]
        assert got["total"] == pytest.approx(exp["total"], abs=0.005)
        assert got["average"] == pytest.approx(exp["average"], abs=0.005)
        for m in months:
            assert got["values"][m] == pytest.approx(exp[m], abs=0.005)
    labels = {r["key"]: r["label"] for r in body["rows"]}
    assert labels["income"] == "1. Renda" and labels["investments"] == "6. Investimentos (− = aportes)"
    assert labels["expenses"] == "4. Despesas"
    assert [r["key"] for r in body["rows"] if r["level"] == 0] == ["income", "tax_provision", "commissions", "expenses",
                                                                 "net_income", "investments"]
    tx = load_taxonomy(CATEGORIES_FIXTURE)
    for r in body["rows"]:
        if r["level"] == 1 and r["key"] in tx.categories:
            assert r["label"] == (tx.categories[r["key"]].get("label_pt") or tx.categories[r["key"]]["label"])


def test_panorama_kpis(api):
    ws, rows = _rows(api)
    months = _months("year:2026")
    t = agg.line_totals(agg.pnl(rows, agg.manual_entries(ws.conn), ws.taxonomy, months), months)
    body = api.get(f"{P}/panorama", params={"period": "year:2026"}).json()
    assert body["months"] == months and len(months) == 10
    assert body["avg_income"] == pytest.approx(t["income"] / 10, abs=0.01)
    assert body["avg_spending"] == pytest.approx(-(t["tax_provision"] + t["commissions"] + t["expenses"]) / 10,
                                                abs=0.01)
    assert body["savings_rate"] == pytest.approx(t["net_income"] / t["income"], abs=1e-4)
    assert set(body) == {"months", "savings_rate", "avg_income", "avg_spending", "categories"}


def test_panorama_categories(api):
    ws, rows = _rows(api)
    body = api.get(f"{P}/panorama", params={"period": "month:2026-10"}).json()
    spark_months = _months("last12")
    exp = agg.expenses_by_category(agg.filter_rows(rows, spark_months))
    assert body["categories"], "fixture has expense categories"
    totals = [c["total"] for c in body["categories"]]
    assert totals == sorted(totals, reverse=True)
    for c in body["categories"]:
        assert c["category_id"] in ws.taxonomy.categories and ws.taxonomy.line_of(c["category_id"]) == "expenses"
        assert len(c["sparkline"]) == 12
        assert c["sparkline"] == [pytest.approx(round(exp[c["category_id"]].get(m, 0.0), 2), abs=0.005) for m in spark_months]
        assert c["total"] == pytest.approx(exp[c["category_id"]].get("2026-10", 0.0), abs=0.005)
        assert c["monthly_avg"] == pytest.approx(c["total"], abs=0.005)  # one month
        assert c["usual"] == insights.usual_for_month(rows, c["category_id"], "2026-10")
        assert c["label"]


def test_sankey_route_balances(api):
    s = api.get(f"{P}/sankey", params={"period": "last12"}).json()
    left = round(sum(n["value"] for n in s["nodes"] if n["side"] == "source") * 100)
    right = round(sum(n["value"] for n in s["nodes"] if n["side"] == "target") * 100)
    mid = [n for n in s["nodes"] if n["side"] == "middle"][0]
    assert left == right == round(mid["value"] * 100) > 0
    assert mid["label"] == "Renda"
    assert all(set(n) == {"id", "label", "side", "key", "value", "filter", "income"} for n in s["nodes"])


def test_channels_parity(api):
    ws, rows = _rows(api)
    months = _months()
    exp = agg.outflows_by_channel(agg.filter_rows(rows, months))
    body = api.get(f"{P}/channels", params={"period": "last12"}).json()
    assert body["months"] == months
    got = {c["method"]: c for c in body["channels"]}
    assert set(got) == set(exp)
    for m, c in got.items():
        assert c["total"] == pytest.approx(sum(exp[m].values()), abs=0.01)
        assert list(c["values"]) == months
        assert c["label"]
    assert list(body["totals"]) == months
    for m in months:
        assert body["totals"][m] == pytest.approx(sum(per.get(m, 0.0) for per in exp.values()), abs=0.01)
    assert [c["total"] for c in body["channels"]] == sorted((c["total"] for c in body["channels"]), reverse=True)


def test_counterparties_parity_names_only(api):
    ws, rows = _rows(api)
    months = _months()
    exp = agg.top_counterparties(agg.filter_rows(rows, months), 20)
    body = api.get(f"{P}/counterparties", params={"period": "last12"}).json()
    assert [(c["name"], c["total"], c["count"]) for c in body["counterparties"]] == exp
    assert set(body["counterparties"][0]) == {"name", "total", "count"}
    assert len(api.get(f"{P}/counterparties", params={"period": "last12", "limit": 1}).json()["counterparties"]) == 1


def test_category_page(api):
    ws, rows = _rows(api)
    cat = api.get(f"{P}/panorama", params={"period": "last12"}).json()["categories"][0]["category_id"]
    api.put(f"{P}/budgets/{cat}", json={"monthly_amount": 321.0}, headers={"X-Finance-Client": "web"})
    body = api.get(f"{P}/categories/{cat}", params={"period": "last12"}).json()
    months = _months()
    exp = agg.expenses_by_category(agg.filter_rows(rows, months))[cat]
    assert [m["month"] for m in body["monthly"]] == months
    assert [m["value"] for m in body["monthly"]] == [pytest.approx(round(exp.get(m, 0.0), 2), abs=0.005) for m in months]
    assert body["total"] == pytest.approx(sum(exp.get(m, 0.0) for m in months), abs=0.01)
    assert body["category_id"] == cat and body["budget"] == 321.0
    assert body["usual"] == insights.usual_for_month(rows, cat, "2026-10")
    assert isinstance(body["top_counterparties"], list)
    r = api.get(f"{P}/categories/nope", params={"period": "last12"})
    assert r.status_code == 404 and set(r.json()) == {"error", "code"}


@pytest.mark.parametrize("path", ["panorama", "sankey", "pnl", "channels", "counterparties", "categories/housing"])
@pytest.mark.parametrize("period", ["bogus", "month:2026-11", "year:2027", "month:2026-13"])
def test_bad_period_is_422(api, path, period):
    r = api.get(f"{P}/{path}", params={"period": period})
    assert r.status_code == 422
    body = r.json()
    assert set(body) == {"error", "code"} and body["code"] == "invalid_period"


def test_year_before_data_is_zero_filled(api):
    body = api.get(f"{P}/pnl", params={"period": "year:2019"}).json()
    assert len(body["months"]) == 12 and body["rows"][0]["total"] == 0


def test_sankey_sobrou_and_filters_match_fixture(api):
    ws, rows = _rows(api)
    for period in ("last12", "month:2026-10", "year:2026"):
        months = _months(period)
        t = agg.line_totals(agg.pnl(rows, agg.manual_entries(ws.conn), ws.taxonomy, months), months)
        s = api.get(f"{P}/sankey", params={"period": period}).json()
        by = {n["key"]: n for n in s["nodes"]}
        net = t["net_income"]
        assert by.get("sobrou", {"value": 0})["value"] == pytest.approx(max(net, 0), abs=0.011)
        assert by.get("reservas_usadas", {"value": 0})["value"] == pytest.approx(max(-net, 0), abs=0.011)
        assert by["renda"]["income"] == pytest.approx(t["income"], abs=0.005)
        if net >= 0:
            assert sum(n["value"] for n in s["nodes"] if n["side"] == "source") == pytest.approx(t["income"], abs=0.011)
        for n in s["nodes"]:
            if n["filter"]:
                got = api.get(f"{P}/transactions", params={**n["filter"], "limit": 5}).json()
                assert got["items"], (n["key"], n["filter"])
