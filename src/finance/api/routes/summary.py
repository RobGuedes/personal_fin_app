import calendar
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from finance import aggregate as agg
from finance import insights
from finance.api.deps import Workspace, get_workspace
from finance.api.models import (
    CategoryStatusOut,
    IncomeSourceOut,
    MonthSummary,
    RendaSplitOut,
    SpendingOut,
    Totals,
    TrendPoint,
)
from finance.api.routes.transactions import review_ids

router = APIRouter()
MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


def local_now() -> datetime:
    return datetime.now(ZoneInfo("America/Sao_Paulo"))


def load_rows(ws: Workspace) -> list[dict]:
    return agg.ledger(ws.conn, ws.taxonomy)


def all_months(rows: list[dict]) -> list[str]:
    current = local_now().strftime("%Y-%m")
    return sorted({r["month"] for r in rows if r["month"] <= current})


def _source_label(key: str, ws: Workspace) -> str:
    """pt-BR label of an income component of `pnl()`: category label, manual entries or uncategorized."""
    if key in ws.taxonomy.categories:
        attrs = ws.taxonomy.categories[key]
        return attrs.get("label_pt") or attrs.get("label", key)
    if key.startswith("manual:"):
        return "Lançamentos manuais"
    if key.startswith(f"{agg.UNCATEGORIZED}:"):
        return "Sem categoria"
    return key


def _shift(month: str, delta: int) -> str:
    n = int(month[:4]) * 12 + int(month[5:7]) - 1 + delta
    return f"{n // 12}-{n % 12 + 1:02d}"


@router.get("/summary/month", response_model=MonthSummary)
def month_summary(month: str | None = Query(None, pattern=MONTH),
                  ws: Workspace = Depends(get_workspace)) -> MonthSummary:
    now = local_now()
    current = now.strftime("%Y-%m")
    month = month or current
    rows = load_rows(ws)
    entries = agg.manual_entries(ws.conn)
    table = agg.pnl(rows, entries, ws.taxonomy, [month])
    totals = agg.line_totals(table, [month])
    days = calendar.monthrange(int(month[:4]), int(month[5:7]))[1]
    is_current = month == current
    day = now.day if is_current else days
    budgets = {r["category_id"]: r["monthly_amount"] for r in ws.conn.execute("SELECT * FROM budgets")}
    notes = {r["transaction_id"]: r["note"] for r in ws.conn.execute("SELECT * FROM transaction_notes")}
    status = insights.compare(rows, month, day, budgets, notes)
    split = insights.renda_split(totals)
    return MonthSummary(
        month=month, day=day, days_in_month=days, is_current=is_current,
        totals=Totals(**{k: totals.get(k, 0.0) for k in Totals.model_fields}),
        renda_split=RendaSplitOut(**vars(split)),
        spending=SpendingOut(
            spent=round(sum(s.spent for s in status), 2),
            reference_to_date=round(sum(s.reference_to_date or 0.0 for s in status), 2),
            reference_month=round(sum(s.reference_month or 0.0 for s in status), 2)),
        categories=[CategoryStatusOut(**vars(s)) for s in status],
        # Same pnl table as totals; breakdown() drops components that net <= 0, so the sum can exceed
        # totals.income only in a month where some income category nets negative.
        income_sources=[IncomeSourceOut(key=k, label=_source_label(k, ws), amount=v)
                        for k, _label, v in agg.breakdown(table, "income", [month])],
        review_count=len(review_ids(ws, rows)))


@router.get("/trend", response_model=list[TrendPoint])
def trend(months: int = Query(6, ge=1, le=60), to: str | None = Query(None, pattern=MONTH),
          ws: Workspace = Depends(get_workspace)) -> list[TrendPoint]:
    current = local_now().strftime("%Y-%m")
    end = min(to or current, current)
    span = [_shift(end, -i) for i in range(months - 1, -1, -1)]
    table = agg.pnl(load_rows(ws), agg.manual_entries(ws.conn), ws.taxonomy, span)
    out = []
    for m in span:
        t = agg.line_totals(table, [m])
        out.append(TrendPoint(month=m, income=t["income"],
                              spending=round(-(t["tax_provision"] + t["commissions"] + t["expenses"]), 2)))
    return out
