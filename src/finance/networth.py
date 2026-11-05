"""Investment positions (Pluggy /investments) and net-worth snapshots.

Groups: accounts (bank balances), investments, crypto (Binance), cards (negative = owed).
A snapshot row is written only for a group whose source succeeded that day; a failed source
is never recorded as 0. `history` carries the last known value of a group forward; a group
with no value yet before its first snapshot counts as 0 in `total`.
"""

import json
import logging
import sqlite3

from finance import aggregate
from finance.sync import _now

log = logging.getLogger(__name__)
GROUPS = ("accounts", "investments", "crypto", "cards")


def sync_investments(conn: sqlite3.Connection, client, item_ids: list[str]) -> int:
    """Store ACTIVE positions per item; positions Pluggy no longer returns (or that are closed)
    are deleted for that item. An item whose fetch raises is left untouched (the error propagates
    before any write for that item). Returns the number of positions stored."""
    n = 0
    for item_id in item_ids:
        positions = client.list_investments(item_id)
        active = [p for p in positions if p.get("status") == "ACTIVE"]
        now = _now()
        with conn:
            for p in active:
                conn.execute(
                    "INSERT INTO investments (id, item_id, name, type, subtype, balance, currency, "
                    "balance_date, raw_json, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET item_id=excluded.item_id, name=excluded.name, "
                    "type=excluded.type, subtype=excluded.subtype, balance=excluded.balance, "
                    "currency=excluded.currency, balance_date=excluded.balance_date, "
                    "raw_json=excluded.raw_json, updated_at=excluded.updated_at",
                    (p["id"], item_id, p.get("name"), p.get("type"), p.get("subtype"), p.get("balance"),
                     p.get("currencyCode"), p.get("date"), json.dumps(p, ensure_ascii=False), now))
            keep = [p["id"] for p in active]
            conn.execute(
                f"DELETE FROM investments WHERE item_id = ? AND id NOT IN ({','.join('?' * len(keep))})",  # noqa: S608
                [item_id, *keep])
        n += len(active)
    return n


def group_totals(conn: sqlite3.Connection) -> dict[str, float]:
    accounts = conn.execute("SELECT COALESCE(SUM(balance), 0) FROM accounts "
                            "WHERE type = 'BANK' AND id != 'binance'").fetchone()[0]
    cards = conn.execute("SELECT COALESCE(SUM(balance), 0) FROM accounts WHERE type = 'CREDIT'").fetchone()[0]
    inv = 0.0
    skipped: dict[str, int] = {}
    for bal, cur in conn.execute("SELECT balance, currency FROM investments"):
        if (cur or "BRL") == "BRL":
            inv += bal or 0.0
        else:
            skipped[cur] = skipped.get(cur, 0) + 1
    for cur, k in skipped.items():
        log.warning("investments: %d position(s) in %s skipped from the BRL total", k, cur)
    holdings = aggregate.binance_holdings(conn)
    return {"accounts": float(accounts), "investments": inv,
            "crypto": holdings["total_brl"] if holdings else 0.0, "cards": -float(cards)}


def snapshot(conn: sqlite3.Connection, day: str, groups: set[str], totals: dict[str, float]) -> None:
    """Upsert `day`'s rows for the given groups only (day = local calendar date)."""
    with conn:
        for g in sorted(groups):
            conn.execute("INSERT INTO net_worth_snapshots (date, grp, value) VALUES (?,?,?) "
                         "ON CONFLICT(date, grp) DO UPDATE SET value = excluded.value", (day, g, totals[g]))


def history(conn: sqlite3.Connection) -> list[dict]:
    by_day: dict[str, dict[str, float]] = {}
    for d, g, v in conn.execute("SELECT date, grp, value FROM net_worth_snapshots ORDER BY date"):
        by_day.setdefault(d, {})[g] = v
    last = {g: 0.0 for g in GROUPS}
    out = []
    for d in sorted(by_day):
        last.update(by_day[d])
        out.append({"date": d, **last, "total": sum(last.values())})
    return out
