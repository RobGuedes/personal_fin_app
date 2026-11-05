"""Consistency checks between reported balances and synced transactions."""

import sqlite3

TOLERANCE = 0.01


def balance_report(conn: sqlite3.Connection) -> list[dict]:
    """One row per account with transactions.

    BANK: history is finite (~12 months), so the check derives the opening balance implied by
    `balance - sum(posted)`. A negative opening balance on an account without overdraft use
    means transactions are missing or have the wrong sign.
    CREDIT: the reported balance should equal the unbilled charges (all PENDING rows, which
    include future installments).
    """
    rows = []
    for acc in conn.execute("SELECT id, name, type, subtype, number_masked, balance FROM accounts "
                           "WHERE id != 'binance' ORDER BY type, name"):
        if acc["type"] == "BANK":
            r = conn.execute(
                "SELECT COUNT(*) n, MIN(date) first, COALESCE(SUM(amount_normalized), 0) total "
                "FROM transactions WHERE account_id = ? AND status = 'POSTED'", (acc["id"],)
            ).fetchone()
            if not r["n"]:
                continue
            opening = round(acc["balance"] - r["total"], 2) + 0.0  # avoid "-0.00"
            rows.append({
                "account": f"{acc['name']} {acc['number_masked']}", "type": "BANK", "balance": acc["balance"],
                "txs": r["n"], "since": r["first"], "computed": round(r["total"], 2),
                "check": f"implied opening balance {opening:.2f} on {r['first']}",
                "ok": opening >= -TOLERANCE,
            })
        else:
            r = conn.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN status = 'PENDING' THEN -amount_normalized END), 0) pending "
                "FROM transactions WHERE account_id = ?", (acc["id"],)
            ).fetchone()
            if not r["n"]:
                continue
            diff = round(acc["balance"] - r["pending"], 2)
            rows.append({
                "account": f"{acc['name']} {acc['number_masked']}", "type": "CREDIT", "balance": acc["balance"],
                "txs": r["n"], "since": None, "computed": round(r["pending"], 2),
                "check": f"balance - unbilled charges = {diff:.2f}",
                "ok": abs(diff) <= TOLERANCE,
            })
    return rows
