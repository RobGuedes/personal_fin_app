from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response

from finance.api.deps import Workspace, get_workspace
from finance.api.errors import ApiError
from finance.api.models import BudgetBody
from finance.api.validation import check_amount

router = APIRouter()

BUDGET_LINES = ("expenses", "commissions")  # spec: expense lines 3-4


def _check(ws: Workspace, category: str) -> None:
    if ws.taxonomy.line_of(category) not in BUDGET_LINES:
        raise ApiError(422, "not_expense_category", f"{category!r} não é uma categoria de despesa.")


@router.get("/budgets")
def list_budgets(ws: Workspace = Depends(get_workspace)) -> dict[str, float]:
    return {r["category_id"]: r["monthly_amount"]
            for r in ws.conn.execute("SELECT category_id, monthly_amount FROM budgets ORDER BY category_id")}


@router.put("/budgets/{category}")
def put_budget(category: str, body: BudgetBody, ws: Workspace = Depends(get_workspace)) -> dict[str, float]:
    _check(ws, category)
    amount = check_amount(body.monthly_amount, positive=True, message="O valor mensal deve ser maior que zero.")
    with ws.conn:
        ws.conn.execute(
            "INSERT INTO budgets (category_id, monthly_amount, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(category_id) DO UPDATE SET monthly_amount = excluded.monthly_amount, "
            "updated_at = excluded.updated_at",
            (category, amount, datetime.now(UTC).isoformat(timespec="seconds")))
    return {category: amount}


@router.delete("/budgets/{category}", status_code=204)
def delete_budget(category: str, ws: Workspace = Depends(get_workspace)) -> Response:
    with ws.conn:
        ws.conn.execute("DELETE FROM budgets WHERE category_id = ?", (category,))
    return Response(status_code=204)
