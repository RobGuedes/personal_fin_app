import copy
from datetime import date

import pytest

from finance.checks import balance_report
from finance.db import connect
from finance.sync import sync
from samples import (
    BANK_BILL_PAYMENT,
    BANK_PIX_IN,
    BANK_PIX_OUT,
    BILL_AUG,
    BILL_OCT,
    CARD_ACCOUNT,
    CARD_BILL_PAYMENT_CREDIT,
    CARD_INSTALLMENT_FUTURE,
    CARD_INSTALLMENT_POSTED,
    CARD_PURCHASE,
    CHECKING_ACCOUNT,
    MY_CPF,
)

TODAY = date(2026, 10, 31)


class FakeClient:
    def __init__(self):
        self.accounts = [copy.deepcopy(CHECKING_ACCOUNT), copy.deepcopy(CARD_ACCOUNT)]
        self.txs = {
            "acc-checking": [copy.deepcopy(t) for t in (BANK_PIX_OUT, BANK_PIX_IN, BANK_BILL_PAYMENT)],
            "acc-card": [copy.deepcopy(t) for t in (CARD_PURCHASE, CARD_BILL_PAYMENT_CREDIT,
                                                   CARD_INSTALLMENT_POSTED, CARD_INSTALLMENT_FUTURE)],
        }
        self.date_from_calls: list = []

    def get_item(self, item_id):
        return {"id": item_id, "connector": {"name": "MeuPluggy"}, "status": "UPDATED"}

    def get_identity(self, item_id):
        return {"document": MY_CPF, "fullName": "FULANO DE TAL"}

    def list_accounts(self, item_id):
        return self.accounts

    def list_bills(self, account_id):
        return [BILL_AUG, BILL_OCT]

    def iter_transactions(self, account_id, date_from=None):
        self.date_from_calls.append((account_id, date_from))
        return iter(self.txs[account_id])


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    yield c
    c.close()


def count(conn, sql="SELECT COUNT(*) FROM transactions"):
    return conn.execute(sql).fetchone()[0]


def test_first_sync_inserts_everything(conn):
    result = sync(conn, FakeClient(), ["item-1"], today=TODAY)
    assert result.errors == []
    assert (result.inserted, result.updated) == (7, 0)
    assert count(conn) == 7
    assert count(conn, "SELECT COUNT(*) FROM bills") == 2
    assert conn.execute("SELECT document FROM identities").fetchone()[0] == MY_CPF


def test_resync_creates_no_duplicates(conn):
    client = FakeClient()
    sync(conn, client, ["item-1"], today=TODAY)
    result = sync(conn, client, ["item-1"], today=TODAY)
    assert (result.inserted, result.updated, result.deleted) == (0, 0, 0)
    assert count(conn) == 7
    assert count(conn, "SELECT COUNT(*) FROM sync_runs WHERE finished_at IS NOT NULL") == 2


def test_first_run_pulls_full_history_then_trailing_window(conn):
    client = FakeClient()
    sync(conn, client, ["item-1"], today=TODAY)
    sync(conn, client, ["item-1"], today=TODAY, window_days=30)
    assert client.date_from_calls[:2] == [("acc-checking", None), ("acc-card", None)]
    # bank: 30 days before its latest stored transaction (29/10 local); card: always full history
    assert client.date_from_calls[2:] == [("acc-checking", date(2026, 9, 29)), ("acc-card", None)]


def test_changed_transaction_is_updated_and_keeps_first_seen(conn):
    client = FakeClient()
    sync(conn, client, ["item-1"], today=TODAY)
    first_seen = conn.execute("SELECT first_seen_at FROM transactions WHERE id='tx-pix-out'").fetchone()[0]
    client.txs["acc-checking"][0]["category"] = "Bookstore"
    result = sync(conn, client, ["item-1"], today=TODAY)
    assert result.updated == 1
    row = conn.execute("SELECT pluggy_category, first_seen_at FROM transactions WHERE id='tx-pix-out'").fetchone()
    assert tuple(row) == ("Bookstore", first_seen)


def test_vanished_pending_charge_is_deleted(conn):
    client = FakeClient()
    sync(conn, client, ["item-1"], today=TODAY)
    client.txs["acc-card"] = [t for t in client.txs["acc-card"] if t["id"] != "tx-inst-10"]
    result = sync(conn, client, ["item-1"], today=TODAY)
    assert result.deleted == 1
    assert count(conn, "SELECT COUNT(*) FROM transactions WHERE id='tx-inst-10'") == 0


def test_vanished_pending_with_manual_classification_is_kept(conn):
    client = FakeClient()
    sync(conn, client, ["item-1"], today=TODAY)
    conn.execute("INSERT INTO classifications VALUES ('tx-inst-10', 'shopping', 'manual', NULL, 1, 'now')")
    conn.commit()
    client.txs["acc-card"] = [t for t in client.txs["acc-card"] if t["id"] != "tx-inst-10"]
    assert sync(conn, client, ["item-1"], today=TODAY).deleted == 0


def test_user_edited_role_survives_resync(conn):
    client = FakeClient()
    sync(conn, client, ["item-1"], today=TODAY)
    conn.execute("UPDATE accounts SET role='investment' WHERE id='acc-checking'")
    conn.commit()
    sync(conn, client, ["item-1"], today=TODAY)
    assert conn.execute("SELECT role FROM accounts WHERE id='acc-checking'").fetchone()[0] == "investment"


def test_failing_item_is_recorded_and_others_continue(conn):
    class Broken(FakeClient):
        def get_item(self, item_id):
            if item_id == "bad":
                raise RuntimeError("boom")
            return super().get_item(item_id)

    result = sync(conn, Broken(), ["bad", "item-1"], today=TODAY)
    assert result.items_synced == 1 and result.errors == ["item 1: RuntimeError: boom"]
    assert count(conn) == 7


def test_balance_report(conn):
    sync(conn, FakeClient(), ["item-1"], today=TODAY)
    report = {r["type"]: r for r in balance_report(conn)}
    # checking: balance 1000 - (-1765.43 + 512.34 - 3210) => opening 5463.09
    assert report["BANK"]["ok"] and "5463.09" in report["BANK"]["check"]
    # card balance 1111.22 == the single pending future installment
    assert report["CREDIT"]["ok"]


def test_reprocess_rebuilds_derived_columns_from_raw(conn):
    from finance.sync import reprocess

    sync(conn, FakeClient(), ["item-1"], today=TODAY)
    first_seen = conn.execute("SELECT first_seen_at FROM transactions WHERE id='tx-pix-out'").fetchone()[0]
    conn.execute("UPDATE transactions SET payment_method='other', date='1999-01-01' WHERE id='tx-pix-out'")
    conn.execute("UPDATE accounts SET role='investment' WHERE id='acc-checking'")
    assert reprocess(conn) == 7
    row = conn.execute("SELECT payment_method, date, first_seen_at FROM transactions WHERE id='tx-pix-out'").fetchone()
    assert tuple(row) == ("pix", "2026-10-29", first_seen)
    assert conn.execute("SELECT role FROM accounts WHERE id='acc-checking'").fetchone()[0] == "investment"


def test_reprocess_skips_binance_rows(conn):
    from finance import binance_normalize as bn
    from finance.sync import _upsert, reprocess

    sync(conn, FakeClient(), ["item-1"], today=TODAY)
    conn.execute("INSERT OR IGNORE INTO items (id, raw_json) VALUES ('binance', '{}')")
    _upsert(conn, "accounts", bn.account_row(None))
    conn.execute("INSERT INTO transactions (id, account_id, date, amount, amount_normalized, payment_method, "
                 "raw_json, first_seen_at, updated_at) VALUES ('binance:dep:2026-10:USDT', 'binance', "
                 "'2026-10-01', 100, 540.0, 'other', '{}', 'x', 'x')")
    assert reprocess(conn) == 7
    assert conn.execute("SELECT amount_normalized FROM transactions WHERE account_id='binance'").fetchone()[0] == 540.0


class NoTxDuringNetworkClient(FakeClient):
    """Fails if a write transaction is open while a 'network' call runs (it would lock API writes)."""

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.checked = 0

    def _check(self):
        assert not self.conn.in_transaction, "write transaction held across a network call"
        self.checked += 1

    def get_identity(self, item_id):
        self._check()
        return super().get_identity(item_id)

    def list_accounts(self, item_id):
        self._check()
        return super().list_accounts(item_id)

    def list_bills(self, account_id):
        self._check()
        return super().list_bills(account_id)

    def iter_transactions(self, account_id, date_from=None):
        self._check()
        return super().iter_transactions(account_id, date_from)


def test_no_write_transaction_across_network_calls(conn):
    client = NoTxDuringNetworkClient(conn)
    result = sync(conn, client, ["item-1", "item-1"], today=TODAY)
    assert result.errors == [] and client.checked >= 8
    assert not conn.in_transaction


def test_connect_sets_busy_timeout(tmp_path):
    c = connect(tmp_path / "t.db")
    assert c.execute("PRAGMA busy_timeout").fetchone()[0] >= 10000


# --- incremental window: what Pluggy's dateFrom really hides --------------------------------------

class DateFilteringClient(FakeClient):
    """Like Pluggy: `date_from` hides every transaction dated before it (UTC day)."""

    def iter_transactions(self, account_id, date_from=None):
        self.date_from_calls.append((account_id, date_from))
        return iter([t for t in self.txs[account_id] if date_from is None or t["date"][:10] >= date_from.isoformat()])


def _posted(pending: dict, new_id: str) -> dict:
    """The POSTED form of a future installment: new id, dated at the purchase date, on a closed bill."""
    tx = copy.deepcopy(pending)
    meta = tx["creditCardMetadata"]
    tx.update(id=new_id, status="POSTED", date=meta["purchaseDate"])
    meta["billId"] = "bill-oct"
    return tx


def test_card_installment_that_posts_backdated_is_not_lost(conn):
    """A PENDING installment turns POSTED dated at the (months old) purchase date: it must still arrive."""
    client = DateFilteringClient()
    sync(conn, client, ["item-1"], today=TODAY)
    pending = next(t for t in client.txs["acc-card"] if t["id"] == "tx-inst-10")
    client.txs["acc-card"] = [t for t in client.txs["acc-card"] if t["id"] != "tx-inst-10"]
    client.txs["acc-card"].append(_posted(pending, "tx-inst-10-posted"))
    sync(conn, client, ["item-1"], today=TODAY)
    rows = conn.execute("SELECT id, status FROM transactions WHERE installment_number = 10").fetchall()
    assert [tuple(r) for r in rows] == [("tx-inst-10-posted", "POSTED")]


def test_card_accounts_always_fetch_full_history(conn):
    client = FakeClient()
    sync(conn, client, ["item-1"], today=TODAY)
    sync(conn, client, ["item-1"], today=TODAY)
    assert ("acc-card", None) in client.date_from_calls[2:]


def test_gap_between_syncs_longer_than_window_is_backfilled(conn):
    client = DateFilteringClient()
    sync(conn, client, ["item-1"], today=TODAY)
    late = copy.deepcopy(BANK_PIX_IN) | {"id": "tx-in-gap", "date": "2026-11-05T03:00:00.000Z"}
    client.txs["acc-checking"].append(late)
    sync(conn, client, ["item-1"], today=date(2026, 12, 15), window_days=30)  # 45 days later
    assert count(conn, "SELECT COUNT(*) FROM transactions WHERE id = 'tx-in-gap'") == 1


def test_manual_decision_on_pending_moves_to_its_posted_row(conn):
    """A hand-classified (or annotated) PENDING charge that posts under a new id must not count twice."""
    client = FakeClient()
    sync(conn, client, ["item-1"], today=TODAY)
    conn.execute("INSERT INTO classifications VALUES ('tx-inst-10', 'shopping', 'manual', NULL, 1, 'now')")
    conn.execute("INSERT INTO transaction_notes VALUES ('tx-inst-10', 'geladeira', 'now')")
    conn.commit()
    pending = next(t for t in client.txs["acc-card"] if t["id"] == "tx-inst-10")
    client.txs["acc-card"] = [t for t in client.txs["acc-card"] if t["id"] != "tx-inst-10"]
    client.txs["acc-card"].append(_posted(pending, "tx-inst-10-posted"))
    sync(conn, client, ["item-1"], today=TODAY)
    assert count(conn, "SELECT COUNT(*) FROM transactions WHERE installment_number = 10") == 1
    cls = conn.execute("SELECT transaction_id, category_id, source FROM classifications "
                       "WHERE transaction_id LIKE 'tx-inst-10%'").fetchall()
    assert [tuple(r) for r in cls] == [("tx-inst-10-posted", "shopping", "manual")]
    note = conn.execute("SELECT transaction_id, note FROM transaction_notes").fetchall()
    assert [tuple(r) for r in note] == [("tx-inst-10-posted", "geladeira")]


def test_manual_pending_without_a_posted_match_is_still_kept(conn):
    client = FakeClient()
    sync(conn, client, ["item-1"], today=TODAY)
    conn.execute("INSERT INTO transaction_notes VALUES ('tx-inst-10', 'geladeira', 'now')")
    conn.commit()
    client.txs["acc-card"] = [t for t in client.txs["acc-card"] if t["id"] != "tx-inst-10"]
    sync(conn, client, ["item-1"], today=TODAY)
    assert count(conn, "SELECT COUNT(*) FROM transaction_notes WHERE transaction_id = 'tx-inst-10'") == 1
