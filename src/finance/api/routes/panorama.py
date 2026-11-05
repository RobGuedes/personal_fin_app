"""Panorama data: KPIs, Sankey, P&L table, channels, counterparties and the category page.

Every figure comes from `aggregate` / `insights`; this module only picks months, localizes labels and shapes JSON.
"""

from fastapi import APIRouter, Depends, Query

from finance import aggregate as agg
from finance import insights
from finance.api.deps import Workspace, get_workspace
from finance.api.errors import ApiError
from finance.api.models import (
    CategoryPageOut,
    ChannelOut,
    ChannelsOut,
    CounterpartiesOut,
    CounterpartyOut,
    MonthValue,
    PanoramaCategory,
    PanoramaOut,
    PnlOut,
    PnlRowOut,
    SankeyOut,
)
from finance.api.routes import summary
from finance.api.routes.summary import _source_label, all_months, load_rows

router = APIRouter()

SPARK_PERIOD = "last12"
METHOD_LABELS = {"pix": "Pix", "ted_doc": "TED/DOC", "boleto": "Boleto", "card": "Cartão de crédito",
                 "debit": "Débito", "fee": "Tarifa", "other": "Outro"}


def _period(period: str, rows: list[dict]) -> list[str]:
    try:
        return insights.period_months(period, summary.local_now().strftime("%Y-%m"), all_months(rows))
    except ValueError:
        raise ApiError(422, "invalid_period",
                       "Período inválido. Use month:AAAA-MM, last12 ou year:AAAA (não depois do mês atual).") from None


def _label(ws: Workspace, key: str) -> str:
    return _source_label(key, ws)


def _localized_table(ws: Workspace, rows: list[dict], months: list[str]) -> list[dict]:
    table = agg.with_totals(agg.pnl(rows, agg.manual_entries(ws.conn), ws.taxonomy, months), months)
    for r in table:
        if r["level"] == 0:
            r["label"] = insights.LINE_LABELS_PT.get(r["key"], r["label"])
        elif r["key"] == "provision":
            r["label"] = "Provisão sobre NF"
        else:
            r["label"] = _label(ws, r["key"])
    return table


def _spent(table: list[dict], key: str, months: list[str]) -> float:
    return round(-sum(r[m] for r in table if r["level"] == 1 and r["key"] == key for m in months), 2)


@router.get("/panorama", response_model=PanoramaOut)
def panorama(period: str = Query("last12"), ws: Workspace = Depends(get_workspace)) -> PanoramaOut:
    rows = load_rows(ws)
    months = _period(period, rows)
    current = summary.local_now().strftime("%Y-%m")
    entries = agg.manual_entries(ws.conn)
    table = _localized_table(ws, rows, months)
    t = agg.line_totals(table, months)
    n = len(months)
    income, spending = t["income"], -(t["tax_provision"] + t["commissions"] + t["expenses"])
    spark_months = insights.period_months(SPARK_PERIOD, current, [])
    spark = agg.pnl(rows, entries, ws.taxonomy, spark_months)
    categories = []
    for r in table:
        if r["level"] != 1 or r["line"] != "expenses" or r["key"] not in ws.taxonomy.categories:
            continue
        total = round(-r["total"], 2)
        series = next((s for s in spark if s["key"] == r["key"]), None)
        categories.append(PanoramaCategory(
            category_id=r["key"], label=r["label"], total=total, monthly_avg=round(total / n, 2),
            sparkline=[round(-series[m], 2) if series else 0.0 for m in spark_months],
            usual=insights.usual_for_month(rows, r["key"], current)))
    categories.sort(key=lambda c: (-c.total, c.category_id))
    return PanoramaOut(
        months=months, savings_rate=round(t["net_income"] / income, 4) if income > 0 else None,
        avg_income=round(income / n, 2), avg_spending=round(spending / n, 2),
        categories=categories)


@router.get("/sankey", response_model=SankeyOut)
def sankey(period: str = Query("last12"), ws: Workspace = Depends(get_workspace)) -> dict:
    rows = load_rows(ws)
    months = _period(period, rows)
    return insights.sankey(_localized_table(ws, rows, months), months)


@router.get("/pnl", response_model=PnlOut)
def pnl(period: str = Query("last12"), ws: Workspace = Depends(get_workspace)) -> PnlOut:
    rows = load_rows(ws)
    months = _period(period, rows)
    table = _localized_table(ws, rows, months)
    return PnlOut(months=months, rows=[
        PnlRowOut(key=r["key"], label=r["label"], level=r["level"], line=r["line"], values={m: r[m] for m in months},
                  total=r["total"], average=r["average"]) for r in table])


@router.get("/channels", response_model=ChannelsOut)
def channels(period: str = Query("last12"), ws: Workspace = Depends(get_workspace)) -> ChannelsOut:
    rows = load_rows(ws)
    months = _period(period, rows)
    by_method = agg.outflows_by_channel(agg.filter_rows(rows, months))
    out = []
    for method, per_month in by_method.items():
        key = method or "other"
        out.append(ChannelOut(method=key, label=METHOD_LABELS.get(key, key),
                              values={m: round(per_month.get(m, 0.0), 2) for m in months},
                              total=round(sum(per_month.values()), 2)))
    out.sort(key=lambda c: (-c.total, c.method))
    totals = {m: round(sum(per_month.get(m, 0.0) for per_month in by_method.values()), 2) for m in months}
    return ChannelsOut(months=months, totals=totals, channels=out)


@router.get("/counterparties", response_model=CounterpartiesOut)
def counterparties(period: str = Query("last12"), limit: int = Query(20, ge=1, le=100),
                   ws: Workspace = Depends(get_workspace)) -> CounterpartiesOut:
    rows = load_rows(ws)
    months = _period(period, rows)
    return CounterpartiesOut(months=months, counterparties=[
        CounterpartyOut(name=n, total=t, count=c)
        for n, t, c in agg.top_counterparties(agg.filter_rows(rows, months), limit)])


@router.get("/categories/{category_id}", response_model=CategoryPageOut)
def category_page(category_id: str, period: str = Query("last12"),
                  ws: Workspace = Depends(get_workspace)) -> CategoryPageOut:
    rows = load_rows(ws)
    months = _period(period, rows)  # validate the period before anything else
    attrs = ws.taxonomy.categories.get(category_id)
    if attrs is None:
        raise ApiError(404, "category_not_found", "Categoria não encontrada.")
    sign = 1 if attrs["line"] == "income" else -1  # spending is reported as a positive amount
    per_month = dict.fromkeys(months, 0.0)
    mine = [r for r in agg.filter_rows(rows, months) if r["category_id"] == category_id]
    for r in mine:
        per_month[r["month"]] += sign * r["amount"]
    budget = ws.conn.execute("SELECT monthly_amount FROM budgets WHERE category_id = ?", (category_id,)).fetchone()
    return CategoryPageOut(
        category_id=category_id, label=attrs.get("label_pt") or attrs.get("label", category_id),
        monthly=[MonthValue(month=m, value=round(v, 2)) for m, v in per_month.items()],
        total=round(sum(per_month.values()), 2),
        usual=insights.usual_for_month(rows, category_id, months[-1]),
        budget=budget["monthly_amount"] if budget else None,
        top_counterparties=[CounterpartyOut(name=n, total=t, count=c) for n, t, c in agg.top_counterparties(mine, 10)])
