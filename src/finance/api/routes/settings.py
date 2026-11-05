"""Ajustes: background sync, transfer audit, rules and manual P&L entries.

Responses carry display names and labels only: never item ids, documents, full account numbers or raw JSON.
"""

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from finance import aggregate as agg
from finance import insights
from finance.api.deps import Workspace, get_workspace
from finance.api.errors import ApiError
from finance.api.models import ManualEntryBody
from finance.api.sync_runner import SyncRunner
from finance.api.validation import NOTE_MAX, check_amount
from finance.classify import classify_all, load_rules_config, parse_rules, remove_rule
from finance.db import connect

router = APIRouter()

MANUAL_LINES = ("income", "tax_provision", "commissions", "expenses", "investments")
LINK_LABELS = {"own_transfer": "Transferência entre contas", "card_bill_payment": "Pagamento de fatura",
               "investment_contribution": "Aplicação", "investment_redemption": "Resgate"}
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DOCS = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{11,}")
RUNS_SHOWN = 5


def _runner(request: Request) -> SyncRunner:
    return request.app.state.sync_runner


def _db_file(ws: Workspace) -> str:
    return next((r["file"] for r in ws.conn.execute("PRAGMA database_list") if r["name"] == "main"), "")


def _category_label(ws: Workspace, category_id: str) -> str:
    attrs = ws.taxonomy.categories.get(category_id, {})
    return attrs.get("label_pt") or attrs.get("label", category_id)


def _mask(text: str | None) -> str | None:
    return DOCS.sub("•••", text) if text else text


# --- sync -----------------------------------------------------------------------------------------

@router.post("/sync", status_code=202)
def start_sync(request: Request, ws: Workspace = Depends(get_workspace)):
    path = _db_file(ws)
    if not path:  # in-memory DB: connect(None) would open FINANCE_DB / data/finance.db instead
        raise ApiError(500, "sync_unavailable", "Sincronização indisponível: o banco de dados não está em um arquivo.")
    if not _runner(request).start(lambda: connect(Path(path)), ws.settings):
        raise ApiError(409, "sync_running", "Uma sincronização já está em andamento.")
    return {"started": True}


def _item_names(ws: Workspace) -> dict[str, str]:
    """{item id: display name} from the item's account names (the connector is always "MeuPluggy")."""
    names: dict[str, dict[str, str]] = {}
    for r in ws.conn.execute("SELECT item_id, institution, name FROM accounts WHERE id != 'binance' ORDER BY rowid"):
        n = (r["institution"] or r["name"] or "").strip()
        if n:
            names.setdefault(r["item_id"], {}).setdefault(n.casefold(), n)
    return {i: " / ".join(d.values()) for i, d in names.items()}


@router.get("/sync/status")
def sync_status(request: Request, ws: Workspace = Depends(get_workspace)) -> dict:
    names = _item_names(ws)
    items = [{"name": _mask(names.get(r["id"]) or r["connector_name"] or "Banco"), "status": r["status"],
              "last_updated_at": r["last_updated_at"]}
             for r in ws.conn.execute("SELECT id, connector_name, status, last_updated_at FROM items "
                                      "WHERE id != 'binance' ORDER BY rowid")]
    runs = []
    for r in ws.conn.execute("SELECT started_at, finished_at, items_synced, inserted, updated, deleted, errors "
                             "FROM sync_runs ORDER BY id DESC LIMIT ?", (RUNS_SHOWN,)):
        try:
            n_errors = len(json.loads(r["errors"])) if r["errors"] else 0
        except ValueError:
            n_errors = 1
        runs.append({k: r[k] for k in ("started_at", "finished_at", "items_synced", "inserted", "updated", "deleted")}
                    | {"error_count": n_errors})
    holdings = agg.binance_holdings(ws.conn)
    return {**_runner(request).status(), "runs": runs, "items": items,
            "binance_snapshot_at": holdings["snapshot_at"] if holdings else None}


# --- transfer audit -------------------------------------------------------------------------------

@router.get("/transfers")
def transfers(ws: Workspace = Depends(get_workspace)) -> list[dict]:
    out = []
    for t in agg.transfer_audit(ws.conn):
        out.append({**t, "link_label": LINK_LABELS.get(t["link_type"], t["link_type"]),
                    "from_description": _mask(t["from_description"]), "to_description": _mask(t["to_description"]),
                    "from_account": _mask(t["from_account"]), "to_account": _mask(t["to_account"])})
    return out


# --- rules ----------------------------------------------------------------------------------------

def _conditions(conditions: dict) -> dict:
    out: dict[str, object] = {}
    for k, v in conditions.items():
        if k == "counterparty_doc":
            out["has_cnpj"] = True  # the document itself never leaves the server
        else:
            out[k] = _mask(v) if isinstance(v, str) else v
    return out


@router.get("/rules")
def list_rules(ws: Workspace = Depends(get_workspace)) -> list[dict]:
    try:
        rules = parse_rules(load_rules_config(ws.rules_path), ws.taxonomy)
    except Exception as e:
        raise ApiError(500, "invalid_rules_file", "O arquivo de regras é inválido.") from e
    return [{"id": r.id, "category_id": r.category, "category_label": _category_label(ws, r.category),
             "conditions": _conditions(r.conditions), "priority": r.priority} for r in rules]


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, ws: Workspace = Depends(get_workspace)) -> dict[str, bool]:
    try:
        removed = remove_rule(rule_id, ws.rules_path, ws.taxonomy)
    except ValueError as e:
        raise ApiError(422, "invalid_rule", "Não foi possível remover a regra sem invalidar o arquivo.") from e
    if not removed:
        raise ApiError(404, "rule_not_found", "Regra não encontrada.")
    classify_all(ws.conn, ws.taxonomy, load_rules_config(ws.rules_path), ws.settings.my_cpf, ws.settings.my_name)
    return {"ok": True}


# --- manual entries -------------------------------------------------------------------------------

def _entry_out(e: dict) -> dict:
    return {"id": e["id"], "month": e["month"], "pnl_line": e["pnl_line"],
            "pnl_line_label": insights.LINE_LABELS_PT.get(e["pnl_line"], e["pnl_line"]),
            "amount": e["amount"], "note": e["note"]}


@router.get("/manual-entries")
def list_manual_entries(ws: Workspace = Depends(get_workspace)) -> list[dict]:
    return [_entry_out(e) for e in agg.manual_entries(ws.conn)]


@router.post("/manual-entries", status_code=201)
def create_manual_entry(body: ManualEntryBody, ws: Workspace = Depends(get_workspace)) -> JSONResponse:
    if not MONTH.match(body.month):
        raise ApiError(422, "invalid_month", "Mês inválido: use AAAA-MM.")
    if body.pnl_line not in MANUAL_LINES:
        raise ApiError(422, "invalid_pnl_line", "Linha do resultado inválida.")
    amount = check_amount(body.amount, positive=False, message="O valor deve ser um número diferente de zero.")
    note = body.note.strip()
    if not note:
        raise ApiError(422, "note_required", "Informe uma descrição.")
    if len(note) > NOTE_MAX:
        raise ApiError(422, "note_too_long", f"A descrição deve ter no máximo {NOTE_MAX} caracteres.")
    with ws.conn:
        new_id = ws.conn.execute("INSERT INTO manual_entries (month, pnl_line, amount, note) VALUES (?, ?, ?, ?)",
                                 (body.month, body.pnl_line, amount, note)).lastrowid
    return JSONResponse(_entry_out({"id": new_id, "month": body.month, "pnl_line": body.pnl_line,
                                    "amount": amount, "note": note}), status_code=201)


@router.delete("/manual-entries/{entry_id}", status_code=204)
def delete_manual_entry(entry_id: int, ws: Workspace = Depends(get_workspace)) -> Response:
    with ws.conn:
        n = ws.conn.execute("DELETE FROM manual_entries WHERE id = ?", (entry_id,)).rowcount
    if not n:
        raise ApiError(404, "manual_entry_not_found", "Lançamento manual não encontrado.")
    return Response(status_code=204)
