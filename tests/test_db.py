import sqlite3
from pathlib import Path

import pytest

from finance import db
from finance.db import MIGRATIONS, connect


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_migration_3_creates_binance_tables(tmp_path):
    conn = connect(tmp_path / "t.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    conn.execute("INSERT INTO fx_rates VALUES ('2026-10-01', 'USDTBRL', 5.33)")
    conn.execute(
        "INSERT INTO binance_positions VALUES "
        "('2026-11-01T00:00:00+00:00', 'earn_flexible', 'USDT', 4321.09, NULL)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO fx_rates VALUES ('2026-10-01', 'USDTBRL', 5.40)")


def test_migration_3_keeps_existing_rows(tmp_path):
    path = tmp_path / "v2.db"
    raw = sqlite3.connect(path)
    with raw:
        for sql in MIGRATIONS[:2]:
            raw.executescript(sql)
        raw.execute("PRAGMA user_version = 2")
        raw.execute(
            "INSERT INTO manual_entries (month, pnl_line, amount, note) "
            "VALUES ('2026-06', 'investments', -1357.91, 'kept')"
        )
    raw.close()

    conn = connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    row = conn.execute("SELECT month, amount, note FROM manual_entries").fetchone()
    assert (row["month"], row["amount"], row["note"]) == ("2026-06", -1357.91, "kept")


def _insert_transaction(conn: sqlite3.Connection, tx_id: str = "tx-1") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO items (id, connector_name, status, last_updated_at, raw_json) "
        "VALUES ('item-1', 'TestConnector', 'UPDATED', NULL, '{}')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO accounts (id, item_id, type, subtype, name, raw_json) "
        "VALUES ('acc-1', 'item-1', 'BANK', 'CHECKING_ACCOUNT', 'Conta', '{}')"
    )
    conn.execute(
        "INSERT INTO transactions (id, account_id, date, amount, amount_normalized, "
        "payment_method, raw_json, first_seen_at, updated_at) "
        "VALUES (?, 'acc-1', '2026-10-01', -10.0, -10.0, 'other', '{}', "
        "'2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z')",
        (tx_id,),
    )


def test_notes_and_budgets_tables(tmp_path):
    conn = db.connect(tmp_path / "x.db")
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"transaction_notes", "budgets"} <= tables

    # budgets.monthly_amount must be strictly positive.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO budgets (category_id, monthly_amount, updated_at) "
            "VALUES ('groceries', 0, '2026-11-01T00:00:00Z')"
        )

    # Deleting a transaction cascades to its note.
    _insert_transaction(conn)
    conn.execute(
        "INSERT INTO transaction_notes (transaction_id, note, updated_at) "
        "VALUES ('tx-1', 'almoço com cliente', '2026-11-01T00:00:00Z')"
    )
    conn.execute("DELETE FROM transactions WHERE id = 'tx-1'")
    remaining = conn.execute("SELECT COUNT(*) FROM transaction_notes").fetchone()[0]
    assert remaining == 0


def test_phase5_migration_is_number_4_on_fresh_db(tmp_path):
    conn = connect(tmp_path / "fresh.db")
    assert len(MIGRATIONS) == 5
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    assert {"fx_rates", "binance_positions", "transaction_notes", "budgets"} <= _tables(conn)


def test_phase5_migration_applies_to_db_at_phase4_version(tmp_path):
    path = tmp_path / "v3.db"
    raw = sqlite3.connect(path)
    with raw:
        for sql in MIGRATIONS[:3]:
            raw.executescript(sql)
        raw.execute("PRAGMA user_version = 3")
    assert "budgets" not in _tables(raw)
    raw.close()

    conn = connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    assert {"fx_rates", "binance_positions", "transaction_notes", "budgets"} <= _tables(conn)


def test_migration_5_from_fresh_and_from_version_4(tmp_path):
    conn = connect(tmp_path / "fresh5.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    assert {"investments", "net_worth_snapshots"} <= _tables(conn)
    path = tmp_path / "v4.db"
    raw = sqlite3.connect(path)
    with raw:
        for sql in MIGRATIONS[:4]:
            raw.executescript(sql)
        raw.execute("PRAGMA user_version = 4")
    assert "investments" not in _tables(raw)
    raw.close()
    conn = connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    assert {"investments", "net_worth_snapshots"} <= _tables(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO net_worth_snapshots VALUES ('2026-11-01', 'bogus', 1)")


def _v4_db(path) -> None:
    raw = sqlite3.connect(path)
    with raw:
        for sql in MIGRATIONS[:4]:
            raw.executescript(sql)
        raw.execute("PRAGMA user_version = 4")
    raw.close()


def test_concurrent_connects_migrate_a_v4_db_once(tmp_path):
    import threading

    path = tmp_path / "v4-race.db"
    _v4_db(path)
    n = 8
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []

    def worker() -> None:
        barrier.wait()
        try:
            connect(path).close()
        except BaseException as exc:  # noqa: BLE001 - collected for the assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    conn = connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    assert {"investments", "net_worth_snapshots"} <= _tables(conn)


def test_failing_migration_leaves_no_partial_table(tmp_path, monkeypatch):
    path = tmp_path / "fail.db"
    connect(path).close()
    bad = "CREATE TABLE half_applied (x INTEGER);\nCREATE TABLE half_applied (x INTEGER);"
    monkeypatch.setattr(db, "MIGRATIONS", [*MIGRATIONS, bad])
    with pytest.raises(sqlite3.OperationalError):
        db.connect(path)
    raw = sqlite3.connect(path)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    assert "half_applied" not in _tables(raw)
    raw.close()


def test_split_statements_keeps_semicolons_in_comments_and_strings():
    sql = "CREATE TABLE a (x TEXT DEFAULT 'a;b'); -- note; here\nCREATE TABLE b (y INTEGER);\n"
    assert len(db._statements(sql)) == 2


def test_tests_never_open_the_real_db(tmp_path_factory):
    """conftest points FINANCE_DB at a temp file for every test: a stray connect() cannot migrate data/finance.db."""
    import os

    from finance.db import DB_PATH
    guard = Path(os.environ["FINANCE_DB"])
    assert guard.resolve() != Path(DB_PATH).resolve()
    assert tmp_path_factory.getbasetemp() in guard.parents
