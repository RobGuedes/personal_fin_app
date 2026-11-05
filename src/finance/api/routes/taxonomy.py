from fastapi import APIRouter, Depends

from finance import aggregate as agg
from finance.api.deps import Workspace, get_workspace
from finance.api.models import CategoryOut, LineOut, TaxonomyOut
from finance.api.routes import summary
from finance.api.routes.summary import load_rows

router = APIRouter()

N_SLOTS = 8  # the validated reference palette (web tokens --cat-0..7)
WINDOW = 12  # complete months the slots are ranked over
OUTFLOW_LINES = ("commissions", "expenses")


def slot_window() -> list[str]:
    """The last WINDOW complete months: the 12 before the current one."""
    current = summary.local_now().strftime("%Y-%m")
    return [summary._shift(current, -i) for i in range(WINDOW, 0, -1)]


def color_slots(ws: Workspace, rows: list[dict], months: list[str]) -> dict[str, int]:
    """Fixed color slot per category from the rankings over `months`: outflows (commissions and expenses,
    ranked together: they share the spending card and doughnut) and income. Uncategorized and manual stay gray."""
    table = agg.pnl(rows, agg.manual_entries(ws.conn), ws.taxonomy, months)
    outflows = sorted((i for line in OUTFLOW_LINES for i in agg.breakdown(table, line, months)
                       if i[0] in ws.taxonomy.categories), key=lambda i: -i[2])
    income = [i for i in agg.breakdown(table, "income", months) if i[0] in ws.taxonomy.categories]
    return {**agg.stable_slots(outflows, N_SLOTS), **agg.stable_slots(income, N_SLOTS)}


@router.get("/taxonomy", response_model=TaxonomyOut)
def taxonomy(ws: Workspace = Depends(get_workspace)) -> TaxonomyOut:
    rows = load_rows(ws)
    slots = color_slots(ws, rows, slot_window())
    tx = ws.taxonomy
    months = summary.all_months(rows)
    return TaxonomyOut(
        first_month=months[0] if months else None,
        lines=[LineOut(id=i, label=label) for i, label in tx.lines.items()],
        categories=[CategoryOut(id=c, line=a["line"], label=a.get("label_pt") or a.get("label", c),
                                icon=a.get("icon") or "•", color_slot=slots.get(c))
                    for c, a in tx.categories.items()])
