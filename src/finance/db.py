"""SQLite schema and migrations (PRAGMA user_version tracks the applied version)."""

import os
import sqlite3
from pathlib import Path

from finance.config import DATA_DIR

DB_PATH = DATA_DIR / "finance.db"
BUSY_TIMEOUT_S = 15  # a writer waits this long for another connection's commit (API + background sync)

# Append new migrations; never edit one that has shipped.
MIGRATIONS = [
    """
    CREATE TABLE items (
        id              TEXT PRIMARY KEY,
        connector_name  TEXT,
        status          TEXT,
        last_updated_at TEXT,
        raw_json        TEXT NOT NULL
    );

    CREATE TABLE identities (
        item_id    TEXT PRIMARY KEY REFERENCES items(id),
        document   TEXT,
        full_name  TEXT,
        raw_json   TEXT NOT NULL
    );

    CREATE TABLE accounts (
        id            TEXT PRIMARY KEY,
        item_id       TEXT NOT NULL REFERENCES items(id),
        type          TEXT,
        subtype       TEXT,
        name          TEXT,
        institution   TEXT,
        number_masked TEXT,
        owner_doc     TEXT,
        currency      TEXT,
        balance       REAL,
        role          TEXT NOT NULL DEFAULT 'other'
                      CHECK (role IN ('checking','savings','credit_card','investment','other')),
        raw_json      TEXT NOT NULL
    );

    CREATE TABLE bills (
        id                 TEXT PRIMARY KEY,
        account_id         TEXT NOT NULL REFERENCES accounts(id),
        due_date           TEXT,
        closing_date       TEXT,
        total_amount       REAL,
        minimum_payment    REAL,
        currency           TEXT,
        raw_json           TEXT NOT NULL
    );

    CREATE TABLE transactions (
        id                  TEXT PRIMARY KEY,
        account_id          TEXT NOT NULL REFERENCES accounts(id),
        date                TEXT NOT NULL,          -- local (America/Sao_Paulo) calendar day
        description         TEXT,
        description_raw     TEXT,
        amount              REAL NOT NULL,          -- as returned by Pluggy
        amount_normalized   REAL NOT NULL,          -- inflow > 0, outflow < 0
        currency            TEXT,
        type                TEXT,                   -- DEBIT | CREDIT
        status              TEXT,                   -- POSTED | PENDING
        operation_type      TEXT,
        pluggy_category     TEXT,
        pluggy_category_id  TEXT,
        counterparty_name   TEXT,
        counterparty_doc    TEXT,
        payment_method      TEXT NOT NULL
                            CHECK (payment_method IN ('card','pix','ted_doc','boleto','debit','fee','other')),
        installment_number  INTEGER,
        installment_total   INTEGER,
        purchase_date       TEXT,
        bill_id             TEXT,
        bill_due_date       TEXT,
        bill_month          TEXT,                   -- YYYY-MM the card charge is billed in
        raw_json            TEXT NOT NULL,
        first_seen_at       TEXT NOT NULL,
        updated_at          TEXT NOT NULL
    );
    CREATE INDEX ix_transactions_account_date ON transactions(account_id, date);
    CREATE INDEX ix_transactions_date ON transactions(date);

    CREATE TABLE classifications (
        transaction_id TEXT PRIMARY KEY REFERENCES transactions(id),
        category_id    TEXT NOT NULL,
        source         TEXT NOT NULL CHECK (source IN ('rule','pluggy_map','transfer_detector','manual')),
        rule_id        TEXT,
        confidence     REAL,
        classified_at  TEXT NOT NULL
    );

    CREATE TABLE transfer_links (
        id                 INTEGER PRIMARY KEY,
        from_transaction_id TEXT NOT NULL REFERENCES transactions(id),
        to_transaction_id   TEXT REFERENCES transactions(id),
        link_type          TEXT NOT NULL CHECK (link_type IN
                           ('own_transfer','card_bill_payment','investment_contribution','investment_redemption')),
        created_at         TEXT NOT NULL,
        UNIQUE (from_transaction_id, to_transaction_id)
    );

    CREATE TABLE manual_entries (
        id       INTEGER PRIMARY KEY,
        month    TEXT NOT NULL,      -- YYYY-MM
        pnl_line TEXT NOT NULL,
        amount   REAL NOT NULL,
        note     TEXT
    );

    CREATE TABLE sync_runs (
        id           INTEGER PRIMARY KEY,
        started_at   TEXT NOT NULL,
        finished_at  TEXT,
        items_synced INTEGER NOT NULL DEFAULT 0,
        inserted     INTEGER NOT NULL DEFAULT 0,
        updated      INTEGER NOT NULL DEFAULT 0,
        deleted      INTEGER NOT NULL DEFAULT 0,
        errors       TEXT
    );
    """,
    # 2: on-device model suggestions for the review queue (never applied automatically).
    """
    CREATE TABLE llm_suggestions (
        transaction_id TEXT PRIMARY KEY REFERENCES transactions(id) ON DELETE CASCADE,
        category_id    TEXT,          -- NULL = the model was unsure
        prompt_version INTEGER NOT NULL,
        created_at     TEXT NOT NULL
    );
    """,
    # 3: Binance prices and holdings snapshots.
    """
    CREATE TABLE fx_rates (
        date  TEXT NOT NULL,          -- local calendar day (America/Sao_Paulo)
        pair  TEXT NOT NULL,          -- e.g. USDTBRL, BTCBRL, OPNUSDT
        close REAL NOT NULL,
        PRIMARY KEY (date, pair)
    );
    CREATE TABLE binance_positions (
        snapshot_at TEXT NOT NULL,    -- ISO timestamp of the sync
        wallet      TEXT NOT NULL,    -- spot | funding | earn_flexible | earn_locked
        asset       TEXT NOT NULL,
        amount      REAL NOT NULL,
        brl_value   REAL,             -- NULL when no price
        PRIMARY KEY (snapshot_at, wallet, asset)
    );
    """,
    # 4: Phase 5 web app: notes and budgets.
    """
    CREATE TABLE transaction_notes (
        transaction_id TEXT PRIMARY KEY REFERENCES transactions(id) ON DELETE CASCADE,
        note           TEXT NOT NULL,
        updated_at     TEXT NOT NULL
    );
    CREATE TABLE budgets (
        category_id    TEXT PRIMARY KEY,
        monthly_amount REAL NOT NULL CHECK (monthly_amount > 0),
        updated_at     TEXT NOT NULL
    );
    """,
    # 5: Phase 5 milestone B: investment positions and net-worth snapshots.
    """
    CREATE TABLE investments (
        id          TEXT PRIMARY KEY,
        item_id     TEXT NOT NULL REFERENCES items(id),
        name        TEXT, type TEXT, subtype TEXT,
        balance     REAL, currency TEXT, balance_date TEXT,
        raw_json    TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE net_worth_snapshots (
        date  TEXT NOT NULL,
        grp   TEXT NOT NULL CHECK (grp IN ('accounts','investments','crypto','cards')),
        value REAL NOT NULL,
        PRIMARY KEY (date, grp)
    );
    """,
]


def connect(path: Path | None = None) -> sqlite3.Connection:
    """`FINANCE_DB` overrides the default path (used by tests)."""
    path = Path(path or os.environ.get("FINANCE_DB") or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=BUSY_TIMEOUT_S)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def _statements(sql: str) -> list[str]:
    """Split a migration script into complete statements (semicolons in strings/comments stay put)."""
    out: list[str] = []
    buf = ""
    for piece in sql.split(";"):
        buf += piece + ";"
        if sqlite3.complete_statement(buf):
            if buf.strip(" \t\r\n;"):
                out.append(buf.strip())
            buf = ""
    if buf.strip(" \t\r\n;"):
        out.append(buf.strip())  # a trailing fragment: let SQLite report it
    return out


def migrate(conn: sqlite3.Connection) -> None:
    """Apply pending migrations atomically, safe against concurrent connections.

    `BEGIN IMMEDIATE` takes the write lock, the version is re-read inside it, and every statement plus the new
    `user_version` commit together (no `executescript`, whose implicit COMMIT would split the transaction).
    """
    if conn.execute("PRAGMA user_version").fetchone()[0] >= len(MIGRATIONS):
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for version, sql in enumerate(MIGRATIONS[current:], start=current + 1):
            for stmt in _statements(sql):
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {version}")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
