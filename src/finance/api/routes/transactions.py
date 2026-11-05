from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query

from finance import aggregate as agg
from finance import llm
from finance.api.deps import Workspace, get_workspace
from finance.api.errors import ApiError
from finance.api.models import TxDetail, TxOut, TxPage, TxPatch
from finance.api.validation import clean_note
from finance.classify import UNCATEGORIZED, set_manual
from finance.search import parse_query
from finance.transfers import fold

router = APIRouter()


def not_found() -> ApiError:
    return ApiError(404, "transaction_not_found", "Transação não encontrada.")


def unknown_category(category_id: str) -> ApiError:
    return ApiError(422, "unknown_category", f"Categoria desconhecida: {category_id!r}.")


def _label(ws: Workspace, row: dict) -> str | None:
    cid = row["category_id"]
    if cid == UNCATEGORIZED:
        return None
    attrs = ws.taxonomy.categories.get(cid, {})
    return attrs.get("label_pt") or attrs.get("label", cid)


def _rows(ws: Workspace) -> list[dict]:
    """Ledger rows (one per transaction id) with the user's notes attached."""
    notes = {r["transaction_id"]: r["note"] for r in ws.conn.execute("SELECT * FROM transaction_notes")}
    labels = agg.account_labels(ws.conn)
    threshold = ws.taxonomy.settings["review_confidence_below"]
    rows = []
    for r in agg.ledger(ws.conn, ws.taxonomy):
        r["account"] = labels.get(r["account_id"], r["account"])
        r["note"] = notes.get(r["id"])
        r["category_label"] = _label(ws, r)
        r["in_review"] = bool(r["category_id"] == UNCATEGORIZED
                              or (r["source"] != "manual" and (r["confidence"] or 0) < threshold))
        rows.append(r)
    rows.sort(key=lambda r: r["id"])
    rows.sort(key=lambda r: r["date"], reverse=True)  # stable: date desc, then id
    return rows


def _out(r: dict) -> TxOut:
    n, t = r["installment_number"], r["installment_total"]
    return TxOut(
        id=r["id"], date=r["date"], month=r["month"], description=r["description"],
        counterparty=r["counterparty_name"] or r["merchant_name"], account=r["account"], amount=r["amount"],
        category_id=r["category_id"], category_label=r["category_label"], line=r["line"],
        excluded=r["line"] == "excluded", installment=f"{n}/{t}" if t and t > 1 and n else None,
        method=r["payment_method"], source=r["source"], note=r["note"], in_review=r["in_review"])


def review_ids(ws: Workspace, rows: list[dict]) -> set[str]:
    """Ids of the review queue: one rule (all months) for Revisar and Início."""
    return {r["id"] for r in agg.review_queue(rows, ws.taxonomy.settings["review_confidence_below"])}


def _matches(r: dict, query) -> bool:
    if query.text:
        hay = fold(" ".join(str(r.get(k) or "") for k in
                            ("description", "counterparty_name", "merchant_name", "note", "account")))
        if query.text not in hay:
            return False
    if query.op:
        a = abs(r["amount"])
        if not ((query.op == ">" and a > query.amount) or (query.op == "<" and a < query.amount)
                or (query.op == "=" and abs(a - query.amount) < 0.005)):
            return False
    return True


@router.get("/transactions", response_model=TxPage)
def list_transactions(q: str = "", month: str | None = None, account: str | None = None,
                      category: str | None = None, line: str | None = None, method: str | None = None,
                      unreviewed: bool = False, cursor: str | None = None,
                      limit: int = Query(100, ge=1, le=500),
                      ws: Workspace = Depends(get_workspace)) -> TxPage:
    query = parse_query(q)
    rows = [r for r in _rows(ws)
            if (not month or r["month"] == month)
            and (not account or account in (r["account_id"], r["account"]))
            and (not category or r["category_id"] == category)
            and (not line or r["line"] == line)
            and (not method or r["payment_method"] == method)
            and (not unreviewed or r["in_review"])
            and _matches(r, query)]
    if cursor:
        date, _, tx_id = cursor.partition("|")
        rows = [r for r in rows if r["date"] < date or (r["date"] == date and r["id"] > tx_id)]
    page = rows[:limit]
    more = len(rows) > limit
    return TxPage(items=[_out(r) for r in page],
                  next_cursor=f"{page[-1]['date']}|{page[-1]['id']}" if more and page else None)


def _detail(ws: Workspace, tx_id: str) -> TxDetail:
    rows = {r["id"]: r for r in _rows(ws)}
    row = rows.get(tx_id)
    if row is None:
        raise not_found()
    link = ws.conn.execute(
        "SELECT from_transaction_id AS f, to_transaction_id AS t FROM transfer_links "
        "WHERE from_transaction_id = ? OR to_transaction_id = ? LIMIT 1", (tx_id, tx_id)).fetchone()
    other = None
    if link:
        other_id = link["t"] if link["f"] == tx_id else link["f"]
        other = rows.get(other_id) if other_id else None
    return TxDetail(**_out(row).model_dump(), pluggy_category=row["pluggy_category"],
                    transfer_pair=_out(other) if other else None,
                    suggestion=llm.stored_suggestions(ws.conn).get(tx_id))


@router.get("/transactions/{tx_id}", response_model=TxDetail)
def get_transaction(tx_id: str, ws: Workspace = Depends(get_workspace)) -> TxDetail:
    return _detail(ws, tx_id)


def set_note(ws: Workspace, tx_id: str, note: str | None) -> None:
    """Save the user's note on a transaction; an empty note removes it."""
    note = clean_note(note)
    with ws.conn:
        if note:
            ws.conn.execute(
                "INSERT INTO transaction_notes (transaction_id, note, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(transaction_id) DO UPDATE SET note = excluded.note, updated_at = excluded.updated_at",
                (tx_id, note, datetime.now(UTC).isoformat(timespec="seconds")))
        else:
            ws.conn.execute("DELETE FROM transaction_notes WHERE transaction_id = ?", (tx_id,))


@router.patch("/transactions/{tx_id}", response_model=TxDetail)
def patch_transaction(tx_id: str, body: TxPatch, ws: Workspace = Depends(get_workspace)) -> TxDetail:
    if not ws.conn.execute("SELECT 1 FROM transactions WHERE id = ?", (tx_id,)).fetchone():
        raise not_found()
    fields = body.model_fields_set
    if "note" in fields:
        clean_note(body.note)  # validate before changing anything
    if body.category_id is not None and body.category_id not in ws.taxonomy.categories:
        raise unknown_category(body.category_id)
    if body.category_id is not None:
        set_manual(ws.conn, tx_id, body.category_id, ws.taxonomy)
    if "note" in fields:
        set_note(ws, tx_id, body.note)
    return _detail(ws, tx_id)
