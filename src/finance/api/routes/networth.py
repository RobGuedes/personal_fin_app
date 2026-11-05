"""Patrimônio: net worth by group, its history, contributions (line 6) and the account list.

Group values come from `networth.group_totals`; the per-account lists are the same rows those totals sum.
Responses carry labels only: never account numbers, position numbers/ISIN/CNPJ, documents or raw JSON.
"""

import re

from fastapi import APIRouter, Depends, Query

from finance import aggregate as agg
from finance import networth
from finance.api.deps import Workspace, get_workspace
from finance.api.models import AccountOut, ContributionsOut, NetWorthAccount, NetWorthGroup, NetWorthOut
from finance.api.routes.panorama import _localized_table, _period
from finance.api.routes.summary import load_rows

router = APIRouter()

GROUP_LABELS = (("investments", "Investimentos"), ("accounts", "Contas"), ("crypto", "Cripto"), ("cards", "Cartões"))
NAME_MAX = 40
DIGITS = re.compile(r"\d{6,}")
FORMATTED = re.compile(r"[\d./-]+")


def _mask_formatted(m: re.Match) -> str:
    return "•••" if sum(c.isdigit() for c in m.group()) >= 8 else m.group()


def _investment_label(name: str | None, institution: str | None) -> str:
    text = FORMATTED.sub(_mask_formatted, (name or "Investimento").strip())
    text = DIGITS.sub("•••", text)
    text = text[:NAME_MAX].rstrip()
    return f"{text} · {institution}" if institution else text


def _accounts(ws: Workspace, grp: str) -> list[NetWorthAccount]:
    conn = ws.conn
    if grp in ("accounts", "cards"):
        labels = agg.account_labels(conn)
        only_banks = "AND a.id != 'binance' " if grp == "accounts" else ""  # constant, no user input
        sql = ("SELECT a.id, a.balance, i.last_updated_at FROM accounts a LEFT JOIN items i "  # noqa: S608
               "ON i.id = a.item_id WHERE a.type = ? " + only_banks + "ORDER BY a.rowid")
        sign = 1 if grp == "accounts" else -1
        return [NetWorthAccount(label=labels[r["id"]], value=sign * (r["balance"] or 0.0),
                                updated_at=r["last_updated_at"])
                for r in conn.execute(sql, ("BANK" if grp == "accounts" else "CREDIT",))]
    if grp == "crypto":
        h = agg.binance_holdings(conn)
        return [NetWorthAccount(label=a, value=v, updated_at=h["snapshot_at"]) for a, v in h["by_asset"]] if h else []
    names: dict[str, dict[str, str]] = {}
    for r in conn.execute("SELECT item_id, institution, name FROM accounts WHERE type = 'BANK' "
                          "AND id != 'binance' ORDER BY rowid"):
        n = (r["institution"] or r["name"] or "").strip()
        if n:
            names.setdefault(r["item_id"], {}).setdefault(n.casefold(), n)
    inst = {i: next(iter(d.values())) for i, d in names.items() if len(d) == 1}
    rows = conn.execute("SELECT item_id, name, balance, updated_at FROM investments "
                        "WHERE COALESCE(currency, 'BRL') = 'BRL' ORDER BY balance DESC, id").fetchall()
    return [NetWorthAccount(label=_investment_label(r["name"], inst.get(r["item_id"])), value=r["balance"] or 0.0,
                            updated_at=r["updated_at"]) for r in rows]


@router.get("/networth", response_model=NetWorthOut)
def net_worth(ws: Workspace = Depends(get_workspace)) -> NetWorthOut:
    totals = networth.group_totals(ws.conn)
    groups = [NetWorthGroup(grp=g, label=label, value=totals[g], accounts=_accounts(ws, g))
              for g, label in GROUP_LABELS]
    stamps = [a.updated_at for g in groups for a in g.accounts if a.updated_at]
    return NetWorthOut(total=sum(g.value for g in groups), groups=groups, as_of=max(stamps) if stamps else None)


@router.get("/networth/history")
def net_worth_history(ws: Workspace = Depends(get_workspace)) -> list[dict]:
    return networth.history(ws.conn)


@router.get("/networth/contributions", response_model=ContributionsOut)
def contributions(period: str = Query("last12"), ws: Workspace = Depends(get_workspace)) -> ContributionsOut:
    rows = load_rows(ws)
    months = _period(period, rows)
    line7 = next(r for r in _localized_table(ws, rows, months) if r["level"] == 0 and r["key"] == "investments")
    return ContributionsOut(months=months, values={m: -line7[m] for m in months}, total=-line7["total"])


@router.get("/accounts", response_model=list[AccountOut])
def accounts(ws: Workspace = Depends(get_workspace)) -> list[AccountOut]:
    labels = agg.account_labels(ws.conn)
    return [AccountOut(id=r["id"], label=labels[r["id"]], type=r["type"], institution=r["institution"])
            for r in ws.conn.execute("SELECT id, type, institution FROM accounts ORDER BY type, name, rowid")]
