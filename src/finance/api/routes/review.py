import logging
import threading
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends

from finance import aggregate as agg
from finance import llm
from finance.api.deps import Workspace, get_workspace
from finance.api.errors import ApiError
from finance.api.models import (
    ConfirmBody,
    ConfirmOut,
    PreviousClassification,
    ReviewItem,
    RuleBody,
    RuleOut,
    Suggestion,
    UndoBody,
)
from finance.api.routes.transactions import _out, _rows, not_found, review_ids, set_note, unknown_category
from finance.api.validation import clean_note
from finance.classify import append_rule, classify_all, load_rules_config, set_manual, suggest_rule
from finance.db import connect

router = APIRouter()
log = logging.getLogger(__name__)

_suggesting = threading.Lock()  # one background suggestion run at a time


# --- helpers --------------------------------------------------------------------------------------

def _tx_dict(ws: Workspace, tx_id: str) -> dict:
    """Fields suggest_rule reads. Never returned to clients (it carries the counterparty document)."""
    row = ws.conn.execute(
        "SELECT amount_normalized AS amount, counterparty_doc, counterparty_name, description, "
        "json_extract(raw_json, '$.merchant.businessName') AS merchant_name FROM transactions WHERE id = ?",
        (tx_id,)).fetchone()
    if row is None:
        raise not_found()
    return dict(row)


def _check_category(ws: Workspace, category_id: str) -> None:
    if category_id not in ws.taxonomy.categories:
        raise unknown_category(category_id)


def create_rule_from(ws: Workspace, tx: dict, category_id: str) -> str:
    """Append a rule built from `tx` to the rules file and re-run the pipeline. Returns the rule id."""
    rule = suggest_rule(tx, category_id)
    if not (rule.get("counterparty_doc") or (rule.get("party") or "").strip()):
        raise ApiError(422, "rule_without_matcher",
                       "Não foi possível criar uma regra: a transação não tem nome nem CNPJ para identificar.")
    try:
        rule_id = append_rule(rule, ws.taxonomy, ws.rules_path)
    except ValueError as e:
        raise ApiError(422, "invalid_rule", f"Regra inválida: {e}") from e
    classify_all(ws.conn, ws.taxonomy, load_rules_config(ws.rules_path), ws.settings.my_cpf, ws.settings.my_name)
    return rule_id


def _category_label(ws: Workspace, category_id: str) -> str:
    attrs = ws.taxonomy.categories.get(category_id, {})
    return attrs.get("label_pt") or attrs.get("label", category_id)


def _party(r: dict) -> str:
    return (r.get("counterparty_name") or r.get("merchant_name") or "").strip().casefold()


def _past_choices(ws: Workspace, rows: list[dict]) -> dict[str, dict]:
    """{counterparty: the latest manual classification row} (by classified_at)."""
    when = {r["transaction_id"]: r["classified_at"] for r in
            ws.conn.execute("SELECT transaction_id, classified_at FROM classifications WHERE source = 'manual'")}
    latest: dict[str, dict] = {}
    for r in rows:
        key = _party(r)
        if (r["source"] == "manual" and key and r["id"] in when
                and (key not in latest or when[r["id"]] > when[latest[key]["id"]])):
            latest[key] = r
    return latest


def _suggestion(ws: Workspace, r: dict, past: dict[str, dict], model: dict[str, str | None]) -> Suggestion | None:
    if r["source"] == "transfer_detector" and r["category_id"] in ws.taxonomy.categories:
        # The detector's current call (paired or one-legged) beats a past choice or a stale model guess.
        return Suggestion(category_id=r["category_id"], reason="transfer", detail="Detectado como transferência")
    if r["source"] not in (None, "manual") and r["category_id"] in ws.taxonomy.categories:
        # A low-confidence Pluggy map / rule category is the current call: show it, not an older model guess.
        return Suggestion(category_id=r["category_id"], reason="current", detail="Categoria atual (confiança baixa)")
    earlier = past.get(_party(r)) if _party(r) else None
    if earlier and earlier["id"] != r["id"]:
        kind = "Pix" if earlier["payment_method"] == "pix" else "Transação"
        day = f"{earlier['date'][8:10]}/{earlier['date'][5:7]}"
        return Suggestion(category_id=earlier["category_id"], reason="past_choice",
                          detail=f"{kind} de {day} para o mesmo nome foi {_category_label(ws, earlier['category_id'])}")
    category = model.get(r["id"])
    if category and category in ws.taxonomy.categories:
        return Suggestion(category_id=category, reason="model", detail="Sugestão do modelo no Mac")
    return None


def _top_categories(rows: list[dict], n: int = 6) -> dict[str, list[str]]:
    counts: dict[str, Counter] = {"in": Counter(), "out": Counter()}
    for r in rows:
        if r["source"] == "manual":
            counts["in" if r["amount"] > 0 else "out"][r["category_id"]] += 1
    return {d: [c for c, _ in counter.most_common(n)] for d, counter in counts.items()}


def _suggest_in_background(db_path: str, taxonomy, missing_ids: set[str]) -> None:
    """Fill llm_suggestions for `missing_ids` with the on-device model; errors are logged and ignored."""
    if not _suggesting.acquire(blocking=False):
        return
    try:
        conn = connect(Path(db_path))
        try:
            rows = agg.ledger(conn, taxonomy)
            queue = [r for r in rows if r["id"] in missing_ids]
            llm.suggest(conn, taxonomy, queue, rows, compile=False)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - suggestions are optional
        log.warning("background suggestions failed", exc_info=True)
    finally:
        _suggesting.release()


def _maybe_start_suggestions(ws: Workspace, missing_ids: set[str]) -> None:
    """Never compiles the helper and never blocks: only runs when the binary already exists."""
    if not missing_ids or not llm.helper_ready():
        return
    db_file = next((r["file"] for r in ws.conn.execute("PRAGMA database_list") if r["name"] == "main"), "")
    if not db_file:
        return
    threading.Thread(target=_suggest_in_background, args=(db_file, ws.taxonomy, missing_ids), daemon=True).start()


# --- routes ---------------------------------------------------------------------------------------

@router.get("/review", response_model=list[ReviewItem])
def inbox(ws: Workspace = Depends(get_workspace)) -> list[ReviewItem]:
    rows = _rows(ws)  # newest first, one row per transaction id
    queue_ids = review_ids(ws, rows)
    queue = [r for r in rows if r["id"] in queue_ids]
    past, model, top = _past_choices(ws, rows), llm.stored_suggestions(ws.conn), _top_categories(rows)
    items = []
    for r in queue:
        s = _suggestion(ws, r, past, model)
        items.append(ReviewItem(**_out(r).model_dump(), suggestion=s,
                                top_categories=top["in" if r["amount"] > 0 else "out"]))
    _maybe_start_suggestions(ws, {i.id for i in items if i.suggestion is None and i.id not in model})
    return items


@router.post("/review/{tx_id}/confirm", response_model=ConfirmOut)
def confirm(tx_id: str, body: ConfirmBody, ws: Workspace = Depends(get_workspace)) -> ConfirmOut:
    tx = _tx_dict(ws, tx_id)
    _check_category(ws, body.category_id)
    if body.note is not None:
        clean_note(body.note)  # validate before changing anything
    prev = ws.conn.execute("SELECT category_id, source, rule_id, confidence FROM classifications "
                           "WHERE transaction_id = ?", (tx_id,)).fetchone()
    prev = dict(prev) if prev else None
    # Rule first: if it cannot be created nothing else has changed (the manual choice wins over it anyway).
    rule_id = create_rule_from(ws, tx, body.category_id) if body.create_rule else None
    set_manual(ws.conn, tx_id, body.category_id, ws.taxonomy)
    if body.note is not None:
        set_note(ws, tx_id, body.note)
    return ConfirmOut(previous=PreviousClassification(**prev) if prev else None, rule_id=rule_id)


@router.post("/review/{tx_id}/undo")
def undo(tx_id: str, body: UndoBody, ws: Workspace = Depends(get_workspace)) -> dict[str, bool]:
    _tx_dict(ws, tx_id)  # 404 if unknown
    prev = body.previous
    with ws.conn:
        if prev is None:
            ws.conn.execute("DELETE FROM classifications WHERE transaction_id = ?", (tx_id,))
        else:
            _check_category(ws, prev.category_id)
            ws.conn.execute(
                "INSERT INTO classifications (transaction_id, category_id, source, rule_id, confidence, classified_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(transaction_id) DO UPDATE SET "
                "category_id = excluded.category_id, source = excluded.source, rule_id = excluded.rule_id, "
                "confidence = excluded.confidence, classified_at = excluded.classified_at",
                (tx_id, prev.category_id, prev.source, prev.rule_id, prev.confidence,
                 datetime.now(UTC).isoformat(timespec="seconds")))
    return {"ok": True}


@router.post("/rules", response_model=RuleOut)
def create_rule(body: RuleBody, ws: Workspace = Depends(get_workspace)) -> RuleOut:
    tx = _tx_dict(ws, body.transaction_id)
    _check_category(ws, body.category_id)
    return RuleOut(rule_id=create_rule_from(ws, tx, body.category_id))
