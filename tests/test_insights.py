import pytest

from finance import insights as ins


def r(id, date, month, amount, category, line="expenses", **kw):
    return {"id": id, "date": date, "month": month, "amount": amount, "category_id": category,
            "line": line, "description": kw.pop("description", ""), "counterparty_name": None, **kw}


def months_rows(cat, amounts, start=(2026, 4), day=10):
    rows = []
    for i, a in enumerate(amounts):
        y, m = start[0], start[1] + i
        mo = f"{y}-{m:02d}"
        rows.append(r(f"{cat}{i}", f"{mo}-{day:02d}", mo, -a, cat))
    return rows


def test_usual_is_median_so_one_offs_do_not_move_it():
    rows = months_rows("housing", [3000, 3000, 9450, 3000, 3000, 3000])
    assert ins.usual_for_month(rows, "housing", "2026-10") == 3000


def test_usual_to_date_caps_day():
    rows = [r("a", "2026-02-28", "2026-02", -100, "food"),
            r("b", "2026-01-05", "2026-01", -100, "food"),
            r("c", "2025-12-05", "2025-12", -100, "food")]
    assert ins.usual_to_date(rows, "food", "2026-03", 31, history=3) == 100


def test_usual_needs_three_months():
    rows = months_rows("housing", [3000, 3000])
    assert ins.usual_for_month(rows, "housing", "2026-06") is None
    assert ins.usual_to_date(rows, "housing", "2026-06", 15) is None


def test_installment_counts_from_day_one():
    assert ins.day_of(r("i", "2026-06-11", "2026-07", -50, "x")) == 1
    assert ins.day_of(r("i", "2026-07-11", "2026-07", -50, "x")) == 11


def test_budget_replaces_usual():
    rows = months_rows("restaurants", [100, 100, 100, 100, 100, 100])
    out = ins.compare(rows, "2026-11", 15, {"restaurants": 1500})
    s = next(c for c in out if c.category_id == "restaurants")
    assert s.reference_to_date == 750 and s.reference_kind == "budget"
    assert s.reference_month == 1500


def test_unusual_needs_25pct_and_300():
    assert ins.is_unusual(1300, 1000)
    assert not ins.is_unusual(1200, 1000)
    assert not ins.is_unusual(390, 100)
    assert not ins.is_unusual(1251, 1000)


def test_unusual_note_uses_note_then_description():
    rows = [r("big", "2026-10-05", "2026-10", -2750, "housing", description="Pix enviado Pix enviado"),
            r("small", "2026-10-06", "2026-10", -100, "housing", description="Luz")]
    assert ins.unusual_note(rows, "housing", "2026-10", 3500, {"big": "ar-condicionado"}) == "ar-condicionado"
    assert ins.unusual_note(rows, "housing", "2026-10", 3500, {}) == "Pix enviado"


def test_renda_split_deficit():
    t = {"income": 10000.0, "expenses": -12000.0, "commissions": -300.0,
         "tax_provision": -600.0, "net_income": -2900.0}
    s = ins.renda_split(t)
    assert s.deficit and s.sobrou == -2900.0
    assert s.outros == 900.0 and s.despesas == 12000.0
    assert s.scale == s.despesas + s.outros == 12900.0


def test_refund_in_history_lowers_usual():
    rows = months_rows("shop", [1000, 1000, 1000])  # Apr..Jun
    assert ins.usual_for_month(rows, "shop", "2026-07", history=3) == 1000
    rows += [r("ref", "2026-04-12", "2026-04", 400, "shop"),
             r("ref2", "2026-05-12", "2026-05", 400, "shop")]  # nets to 600, 600, 1000
    assert ins.usual_for_month(rows, "shop", "2026-07", history=3) == 600
    assert ins.usual_to_date(rows, "shop", "2026-07", 31, history=3) == 600


def test_compare_flags_unusual_with_pct_and_note():
    rows = months_rows("housing", [1000] * 6, start=(2026, 4))
    rows += [r("ac", "2026-10-05", "2026-10", -2750, "housing", description="Pix enviado Ar"),
             r("late", "2026-10-25", "2026-10", -5000, "housing", description="Later"),
             r("ref", "2026-10-06", "2026-10", 50, "housing")]
    out = ins.compare(rows, "2026-10", 20, {}, notes={"ac": "ar-condicionado"})
    s = next(c for c in out if c.category_id == "housing")
    assert s.spent == 2700 and s.reference_kind == "usual"
    assert s.reference_to_date == 1000 and s.reference_month == 1000
    assert s.unusual and abs(s.pct_over - 1.7) < 1e-9
    assert s.note == "ar-condicionado"


def test_budget_reference_caps_day_and_ties_sorted():
    rows = [r("a", "2026-11-01", "2026-11", -10, "zeta"), r("b", "2026-11-01", "2026-11", -10, "alpha")]
    out = ins.compare(rows, "2026-11", 45, {"zeta": 3000})
    assert next(c for c in out if c.category_id == "zeta").reference_to_date == 3000
    assert [c.category_id for c in out] == ["alpha", "zeta"]


# --- period_months / sankey (Milestone B, Task 4) ------------------------------------------------



def test_period_months_month_and_last12():
    assert ins.period_months("month:2026-03", "2026-10", ["2026-01"]) == ["2026-03"]
    last = ins.period_months("last12", "2026-10", ["2026-09", "2026-10"])  # sparse data: still 12, zero-filled
    assert last[0] == "2025-11" and last[-1] == "2026-10" and len(last) == 12
    assert ins.period_months("last12", "2026-01", []) [0] == "2025-02"


def test_period_months_year_capped_at_current_and_zero_filled():
    assert ins.period_months("year:2026", "2026-10", ["2026-05"]) == [f"2026-{m:02d}" for m in range(1, 11)]
    assert ins.period_months("year:2025", "2026-10", ["2026-05"]) == [f"2025-{m:02d}" for m in range(1, 13)]
    assert ins.period_months("year:2020", "2026-10", ["2026-05"]) == [f"2020-{m:02d}" for m in range(1, 13)]


@pytest.mark.parametrize("period", ["", "last6", "month:2026-13", "month:2026-11", "year:2027", "year:26", "month:abcd-ef",
                                    "year:2026-01", "LAST12"])
def test_period_months_rejects_bad_or_future(period):
    with pytest.raises(ValueError):
        ins.period_months(period, "2026-10", ["2026-05"])


def _table(months, lines, comps):
    """pnl-shaped table: `lines` {line: per-month value}, `comps` [(line, key, label, value)] (value spread on first month)."""
    rows = []
    for line, v in lines.items():
        rows.append({"key": line, "label": line, "level": 0, "line": line, **{m: (v if m == months[0] else 0.0) for m in months}})
    for line, key, label, v in comps:
        rows.append({"key": key, "label": label, "level": 1, "line": line, **{m: (v if m == months[0] else 0.0) for m in months}})
    return rows


def _check_balance(s):
    left = round(sum(n["value"] for n in s["nodes"] if n["side"] == "source") * 100)
    right = round(sum(n["value"] for n in s["nodes"] if n["side"] == "target") * 100)
    mid = [n for n in s["nodes"] if n["side"] == "middle"]
    assert len(mid) == 1
    assert left == right == round(mid[0]["value"] * 100)
    by_id = {n["id"]: n for n in s["nodes"]}
    for n in s["nodes"]:
        flow = sum(l["value"] for l in s["links"] if (l["source"] if n["side"] != "target" else l["target"]) == n["id"])
        if n["side"] == "middle":
            inflow = sum(l["value"] for l in s["links"] if l["target"] == n["id"])
            assert round(inflow * 100) == round(n["value"] * 100) == round(flow * 100)
        else:
            assert round(flow * 100) == round(n["value"] * 100)
    assert all(l["source"] in by_id and l["target"] in by_id for l in s["links"])


def test_sankey_surplus_month_balances_with_drifting_floats():
    months = ["2026-10"]
    inc = [(f"inc{i}", 100.1 * (i + 1) / 3) for i in range(8)]
    exp = [(f"exp{i}", -(33.33 + i * 7.77)) for i in range(9)]
    income = round(sum(v for _k, v in inc), 2)
    e5 = round(sum(v for _k, v in exp), 2)
    table = _table(months, {"income": income, "tax_provision": -61.37, "commissions": -120.11,
                            "expenses": e5, "net_income": 0.0},
                   [("income", k, k.upper(), round(v, 2)) for k, v in inc]
                   + [("expenses", k, k.upper(), round(v, 2)) for k, v in exp])
    s = ins.sankey(table, months)
    _check_balance(s)
    sources = [n for n in s["nodes"] if n["side"] == "source"]
    assert len(sources) == 6 and sources[-1]["key"] == "outras_rendas"  # top 5 + Outras
    targets = [n for n in s["nodes"] if n["side"] == "target"]
    assert [n["key"] for n in targets[:3]] == ["sobrou", "commissions", "tax_provision"]
    assert targets[-1]["key"] == "outras_despesas" and len(targets) == 3 + 6 + 1
    assert not any(n["key"] == "reservas_usadas" for n in s["nodes"])
    assert all(n["value"] > 0 for n in s["nodes"])


def test_sankey_deficit_month_uses_reservas():
    months = ["2026-09", "2026-10"]
    table = _table(months, {"income": 1000.0, "tax_provision": -60.0, "commissions": -300.0,
                            "expenses": -1500.0}, [("income", "services_nf", "Serviços", 1000.0),
                                                   ("expenses", "housing", "Moradia", -1500.0)])
    s = ins.sankey(table, months)
    _check_balance(s)
    keys = {n["key"]: n for n in s["nodes"]}
    assert keys["reservas_usadas"]["value"] == 860.0 and keys["reservas_usadas"]["side"] == "source"
    assert "sobrou" not in keys
    assert keys["renda"]["value"] == 1860.0  # equals everything flowing out on the right
    assert keys["tax_provision"]["value"] == 60.0 and keys["housing"]["value"] == 1500.0


def test_sankey_skips_zero_nodes_and_empty():
    months = ["2026-10"]
    table = _table(months, {"income": 500.0, "tax_provision": 0.0, "commissions": 0.0, "expenses": -500.0},
                   [("income", "services_nf", "Serviços", 500.0), ("expenses", "housing", "Moradia", -500.0)])
    s = ins.sankey(table, months)
    assert {n["key"] for n in s["nodes"]} == {"services_nf", "renda", "housing"}
    _check_balance(s)
    empty = ins.sankey(_table(months, {"income": 0.0, "tax_provision": 0.0, "commissions": 0.0,
                                       "expenses": 0.0}, []), months)
    assert empty == {"nodes": [], "links": []}


def _line5(totals):
    return round(sum(totals[k] for k in ("income", "tax_provision", "commissions", "expenses")), 2)


def _by_key(s):
    return {n["key"]: n for n in s["nodes"]}


def test_sankey_refund_category_keeps_sobrou_equal_to_line5():
    months = ["2026-10"]
    table = _table(months, {"income": 1000.0, "tax_provision": 0.0, "commissions": 0.0, "expenses": -500.0},
                   [("income", "services_nf", "Serviços", 1000.0), ("expenses", "housing", "Moradia", -800.0),
                    ("expenses", "shopping", "Compras", 300.0)])
    s = ins.sankey(table, months)
    _check_balance(s)
    k = _by_key(s)
    assert k["sobrou"]["value"] == 500.0 and k["housing"]["value"] == 500.0
    assert k["renda"]["value"] == 1000.0 and k["renda"]["income"] == 1000.0


def test_sankey_negative_income_component():
    months = ["2026-10"]
    table = _table(months, {"income": 700.0, "tax_provision": 0.0, "commissions": 0.0, "expenses": -200.0},
                   [("income", "services_nf", "Serviços", 1000.0), ("income", "dividends", "Dividendos", -300.0),
                    ("expenses", "housing", "Moradia", -200.0)])
    s = ins.sankey(table, months)
    _check_balance(s)
    k = _by_key(s)
    assert k["sobrou"]["value"] == 500.0
    assert sum(n["value"] for n in s["nodes"] if n["side"] == "source") == 700.0


def test_sankey_net_positive_line_node():
    months = ["2026-10"]
    table = _table(months, {"income": 1000.0, "tax_provision": -100.0, "commissions": 50.0,
                            "expenses": -400.0}, [("income", "services_nf", "Serviços", 1000.0),
                                                  ("expenses", "housing", "Moradia", -400.0)])
    s = ins.sankey(table, months)
    _check_balance(s)
    k = _by_key(s)
    assert "commissions" not in k and k["sobrou"]["value"] == 550.0 and k["tax_provision"]["value"] == 100.0
    assert k["housing"]["value"] == 350.0  # the +50 commissions inflow nets against the largest band


def test_sankey_node_filters():
    months = ["2026-10"]
    table = _table(months, {"income": 1000.0, "tax_provision": -60.0, "commissions": -100.0,
                            "expenses": -300.0},
                   [("income", "services_nf", "Serviços", 1000.0), ("expenses", "uncategorized:expenses", "Sem", -100.0),
                    ("expenses", "manual:expenses", "Manual", -100.0), ("expenses", "housing", "Moradia", -100.0)])
    k = _by_key(ins.sankey(table, months))
    assert k["uncategorized:expenses"]["filter"] == {"category": "uncategorized", "line": "expenses"}
    assert k["manual:expenses"]["filter"] is None and k["sobrou"]["filter"] is None and k["renda"]["filter"] is None
    assert k["commissions"]["filter"] == {"line": "commissions"} and k["tax_provision"]["filter"] is None
    assert k["housing"]["filter"] == {"category": "housing"} and k["services_nf"]["filter"] == {"category": "services_nf"}


def test_period_months_rejects_trailing_newline():
    with pytest.raises(ValueError):
        ins.period_months("month:2026-03\n", "2026-10", [])
