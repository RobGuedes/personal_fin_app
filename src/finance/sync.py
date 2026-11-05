"""Pull Pluggy data into SQLite. Idempotent (upsert by Pluggy id) and incremental.

Card (CREDIT) accounts are always pulled in full: a future installment turns POSTED dated at its (months
old) purchase date, outside any trailing window. Bank accounts pull their full history on the first run,
then from `window_days` before the newer of "today" and their latest stored transaction, so a gap between
syncs longer than the window is backfilled.

PENDING rows inside the fetched range that Pluggy no longer returns are deleted (a posted charge can come
back under a new id). A stale row carrying a user decision (manual classification or note) is never just
deleted: the decision moves to the matching new row, else the row is kept for review.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from finance.binance_normalize import ACCOUNT_ID as BINANCE_ACCOUNT_ID
from finance.normalize import account_row, bill_row, digits, dumps, transaction_row
from finance.pluggy_client import PluggyClient

DEFAULT_WINDOW_DAYS = 30
# A stale PENDING charge (not an installment) matches a new row of the same amount within this many days.
POSTED_MATCH_DAYS = 7
# Pluggy's dateFrom filter is UTC-based while stored dates are local; keep a margin so a row
# just outside what was re-fetched is never mistaken for a vanished pending charge.
STALE_PENDING_MARGIN_DAYS = 2


@dataclass
class SyncResult:
    items_synced: int = 0
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    errors: list[str] = field(default_factory=list)
    accounts: list[dict] = field(default_factory=list)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _upsert(conn: sqlite3.Connection, table: str, row: dict, keep: tuple[str, ...] = ()) -> None:
    """INSERT or UPDATE by id; columns in `keep` are only written on insert."""
    cols = list(row)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "id" and c not in keep)
    # table and columns are code constants (row dicts from normalize); every value is a bound parameter
    conn.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "  # noqa: S608
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        [row[c] for c in cols],
    )


def _upsert_transaction(conn: sqlite3.Connection, row: dict, now: str) -> str:
    """Returns 'inserted', 'updated' or 'unchanged'."""
    existing = conn.execute("SELECT raw_json FROM transactions WHERE id = ?", (row["id"],)).fetchone()
    if existing and existing["raw_json"] == row["raw_json"]:
        return "unchanged"
    _upsert(conn, "transactions", {**row, "first_seen_at": now, "updated_at": now}, keep=("first_seen_at",))
    return "updated" if existing else "inserted"


def _has_user_data(conn: sqlite3.Connection, tx_id: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM classifications WHERE transaction_id = ? AND source = 'manual' "
        "UNION ALL SELECT 1 FROM transaction_notes WHERE transaction_id = ?", (tx_id, tx_id)).fetchone())


def _posted_match(conn: sqlite3.Connection, tx_id: str, candidates: set[str], claimed: set[str]) -> str | None:
    """The new row (inserted by this sync) that is the posted form of the stale PENDING row `tx_id`."""
    old = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    best = None
    for c in candidates - claimed:
        new = conn.execute("SELECT * FROM transactions WHERE id = ?", (c,)).fetchone()
        if new is None or new["account_id"] != old["account_id"] or _has_user_data(conn, c):
            continue
        if round(new["amount_normalized"] - old["amount_normalized"], 2) != 0:
            continue
        gap = abs((date.fromisoformat(new["date"]) - date.fromisoformat(old["date"])).days)
        if (old["installment_total"] or 0) > 1:
            same = all(new[k] == old[k] for k in ("installment_number", "installment_total", "purchase_date"))
            if not same:
                continue
        elif gap > POSTED_MATCH_DAYS:
            continue
        if best is None or gap < best[0]:
            best = (gap, c)
    return best[1] if best else None


def _delete_transaction(conn: sqlite3.Connection, tx_id: str) -> None:
    conn.execute("DELETE FROM classifications WHERE transaction_id = ?", (tx_id,))
    conn.execute("DELETE FROM transaction_notes WHERE transaction_id = ?", (tx_id,))
    conn.execute("DELETE FROM transfer_links WHERE from_transaction_id = ? OR to_transaction_id = ?", (tx_id, tx_id))
    conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))


def _delete_stale_pending(conn: sqlite3.Connection, account_id: str, seen: set[str], since: date | None,
                          inserted: set[str] | frozenset[str] = frozenset()) -> int:
    query = "SELECT id FROM transactions WHERE account_id = ? AND status = 'PENDING'"
    params: list = [account_id]
    if since:
        query += " AND date >= ?"
        params.append((since + timedelta(days=STALE_PENDING_MARGIN_DAYS)).isoformat())
    stale = [r["id"] for r in conn.execute(query, params) if r["id"] not in seen]
    deleted = 0
    claimed: set[str] = set()
    for tx_id in stale:
        if _has_user_data(conn, tx_id):
            # Never discard a user decision: move it to the posted row, else keep the row for review.
            match = _posted_match(conn, tx_id, set(inserted), claimed)
            if match is None:
                continue
            claimed.add(match)
            conn.execute("DELETE FROM classifications WHERE transaction_id = ?", (match,))
            conn.execute("UPDATE classifications SET transaction_id = ? WHERE transaction_id = ? AND source = 'manual'",
                         (match, tx_id))
            conn.execute("UPDATE transaction_notes SET transaction_id = ? WHERE transaction_id = ?", (match, tx_id))
        _delete_transaction(conn, tx_id)
        deleted += 1
    return deleted


def _fetch_since(conn: sqlite3.Connection, acc: dict, window_days: int, today: date) -> date | None:
    """None = full history (first run, or a card account); else the start of the re-fetched range."""
    if acc.get("type") == "CREDIT":
        return None
    last = conn.execute("SELECT MAX(date) FROM transactions WHERE account_id = ? AND date <= ?",
                        (acc["id"], today.isoformat())).fetchone()[0]
    if last is None:
        has_rows = conn.execute("SELECT 1 FROM transactions WHERE account_id = ? LIMIT 1", (acc["id"],)).fetchone()
        return today - timedelta(days=window_days) if has_rows else None
    return min(today, date.fromisoformat(last)) - timedelta(days=window_days)


def _sync_item(conn: sqlite3.Connection, client: PluggyClient, item_id: str, window_days: int,
               today: date, result: SyncResult) -> None:
    """Fetch the whole item first, then write it in one short transaction.

    No write transaction is open during network calls, so the API (another connection) can keep writing
    during a long sync; a failing fetch still leaves the item untouched (all-or-nothing per item)."""
    now = _now()
    item = client.get_item(item_id)
    identity = client.get_identity(item_id)
    fetched = []
    for acc in client.list_accounts(item_id):
        bills = list(client.list_bills(acc["id"])) if acc.get("type") == "CREDIT" else []
        since = _fetch_since(conn, acc, window_days, today)
        fetched.append((acc, bills, since, list(client.iter_transactions(acc["id"], date_from=since))))

    _upsert(conn, "items", {
        "id": item["id"],
        "connector_name": (item.get("connector") or {}).get("name"),
        "status": item.get("status"),
        "last_updated_at": item.get("lastUpdatedAt"),
        "raw_json": dumps(item),
    })
    if identity:
        conn.execute(
            "INSERT INTO identities (item_id, document, full_name, raw_json) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(item_id) DO UPDATE SET document = excluded.document, "
            "full_name = excluded.full_name, raw_json = excluded.raw_json",
            (item_id, digits(identity.get("document")), identity.get("fullName"), dumps(identity)),
        )

    for acc, bills, since, txs in fetched:
        row = account_row(acc)
        _upsert(conn, "accounts", row, keep=("role",))  # role is user-editable

        bill_due_dates: dict[str, str] = {}
        if acc.get("type") == "CREDIT":
            for bill in bills:
                _upsert(conn, "bills", bill_row(bill, acc["id"]))
            bill_due_dates = {
                r["id"]: r["due_date"]
                for r in conn.execute("SELECT id, due_date FROM bills WHERE account_id = ?", (acc["id"],))
            }

        seen: set[str] = set()
        inserted: set[str] = set()
        counts = {"inserted": 0, "updated": 0, "unchanged": 0}
        for tx in txs:
            seen.add(tx["id"])
            outcome = _upsert_transaction(conn, transaction_row(tx, acc.get("type", ""), bill_due_dates), now)
            counts[outcome] += 1
            if outcome == "inserted":
                inserted.add(tx["id"])
        deleted = _delete_stale_pending(conn, acc["id"], seen, since, inserted)

        result.inserted += counts["inserted"]
        result.updated += counts["updated"]
        result.deleted += deleted
        result.accounts.append({
            "name": row["name"], "subtype": row["subtype"], "number": row["number_masked"],
            "mode": "full history" if since is None else f"since {since.isoformat()}",
            "fetched": len(seen), **counts, "deleted": deleted,
        })
    conn.commit()


def reprocess(conn: sqlite3.Connection) -> int:
    """Rebuild derived columns of accounts, bills and transactions from stored raw JSON (no API calls).
    Binance rows are skipped: their raw JSON is not Pluggy's and their BRL value needs prices."""
    for r in conn.execute("SELECT raw_json FROM accounts WHERE id != ?", (BINANCE_ACCOUNT_ID,)).fetchall():
        _upsert(conn, "accounts", account_row(json.loads(r["raw_json"])), keep=("role",))
    for r in conn.execute("SELECT account_id, raw_json FROM bills").fetchall():
        _upsert(conn, "bills", bill_row(json.loads(r["raw_json"]), r["account_id"]))
    due = {r["id"]: r["due_date"] for r in conn.execute("SELECT id, due_date FROM bills")}
    types = {r["id"]: r["type"] for r in conn.execute("SELECT id, type FROM accounts")}
    rows = conn.execute("SELECT account_id, raw_json FROM transactions WHERE account_id != ?",
                        (BINANCE_ACCOUNT_ID,)).fetchall()
    for r in rows:
        row = transaction_row(json.loads(r["raw_json"]), types[r["account_id"]], due)
        _upsert(conn, "transactions", {**row, "first_seen_at": _now(), "updated_at": _now()},
                keep=("first_seen_at", "updated_at"))
    conn.commit()
    return len(rows)


def sync(conn: sqlite3.Connection, client: PluggyClient, item_ids: list[str],
         window_days: int = DEFAULT_WINDOW_DAYS, today: date | None = None) -> SyncResult:
    today = today or date.today()
    result = SyncResult()
    run_id = conn.execute("INSERT INTO sync_runs (started_at) VALUES (?)", (_now(),)).lastrowid
    conn.commit()
    for n, item_id in enumerate(item_ids, 1):
        try:
            _sync_item(conn, client, item_id, window_days, today, result)
            result.items_synced += 1
        except Exception as exc:  # one failing item must not block the others
            conn.rollback()
            result.errors.append(f"item {n}: {type(exc).__name__}: {exc}")
    conn.execute(
        "UPDATE sync_runs SET finished_at = ?, items_synced = ?, inserted = ?, updated = ?, deleted = ?, "
        "errors = ? WHERE id = ?",
        (_now(), result.items_synced, result.inserted, result.updated, result.deleted,
         json.dumps(result.errors) if result.errors else None, run_id),
    )
    conn.commit()
    return result
