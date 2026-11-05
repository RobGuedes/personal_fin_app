from finance.checks import balance_report
from finance.db import connect


def test_balance_report_skips_binance(tmp_path):
    conn = connect(tmp_path / "t.db")
    conn.execute("INSERT INTO items (id, raw_json) VALUES ('binance', '{}')")
    conn.execute("INSERT INTO accounts (id, item_id, type, subtype, name, balance, raw_json) "
                 "VALUES ('binance', 'binance', 'BANK', 'BINANCE', 'Binance', 1000, '{}')")
    conn.execute("INSERT INTO transactions (id, account_id, date, amount, amount_normalized, payment_method, "
                 "status, raw_json, first_seen_at, updated_at) VALUES ('b1', 'binance', '2026-10-01', 5, 5, "
                 "'other', 'POSTED', '{}', 'a', 'b')")
    conn.execute("INSERT INTO items (id, raw_json) VALUES ('item-1', '{}')")
    conn.execute("INSERT INTO accounts (id, item_id, type, subtype, name, balance, raw_json) "
                 "VALUES ('acc-1', 'item-1', 'BANK', 'CHECKING_ACCOUNT', 'Itau', 5, '{}')")
    conn.execute("INSERT INTO transactions (id, account_id, date, amount, amount_normalized, payment_method, "
                 "status, raw_json, first_seen_at, updated_at) VALUES ('p1', 'acc-1', '2026-10-01', 5, 5, "
                 "'pix', 'POSTED', '{}', 'a', 'b')")
    conn.commit()
    assert [r["account"].split()[0] for r in balance_report(conn)] == ["Itau"]
