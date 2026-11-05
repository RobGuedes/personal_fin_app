from collections import Counter

from binance_samples import (
    AIRDROP,
    DEPOSIT,
    FAKE_ADDRESS,
    FIAT_DEPOSIT,
    REWARD_D1,
    REWARD_D2,
    WITHDRAWAL,
)
from finance import normalize
from finance.binance_normalize import (
    ACCOUNT_ID,
    account_row,
    deposit_row,
    earn_rows,
    fiat_row,
    is_unpriced,
    item_row,
    local_day,
    mask_address,
    withdrawal_row,
)

RATE = lambda asset, day: {"USDT": 5.0, "BTC": 600_000.0, "BRL": 1.0}.get(asset)

TX_KEYS = set(normalize.transaction_row(
    {"id": "x", "accountId": "a", "date": "2026-01-01T12:00:00Z", "amount": 1.0}, "BANK", {}
))


def test_deposit_row():
    r = deposit_row(DEPOSIT, RATE)
    assert r["id"] == "binance:dep:FAKEDEP0000000001"
    assert r["amount"] == 456.78
    assert r["amount_normalized"] == 2283.9
    assert r["currency"] == "USDT"
    assert r["description"] == "Binance deposit USDT (TRX)"
    assert r["type"] == "CREDIT"
    assert r["payment_method"] == "other"
    assert r["status"] == "POSTED"
    assert r["account_id"] == ACCOUNT_ID == "binance"
    assert r["date"] == "2026-10-01"
    assert set(r) == TX_KEYS
    assert r["raw_json"] == normalize.dumps(DEPOSIT)


def test_withdrawal_includes_fee_and_masks_address():
    r = withdrawal_row(WITHDRAWAL, RATE)
    assert r["id"] == "binance:wd:FAKEWD0000000000000000000000001"
    assert r["amount"] == -654.33
    assert r["amount_normalized"] == -3271.65
    assert r["type"] == "DEBIT"
    assert r["description"].endswith("→ …9001")
    assert r["counterparty_name"] == "…9001"
    assert r["date"] == "2026-07-06"
    assert set(r) == TX_KEYS
    for k, v in r.items():
        if k != "raw_json":
            assert FAKE_ADDRESS not in str(v)


def test_incomplete_statuses_are_skipped():
    assert deposit_row({**DEPOSIT, "status": 0}, RATE) is None
    assert withdrawal_row({**WITHDRAWAL, "status": 4}, RATE) is None
    assert fiat_row({**FIAT_DEPOSIT, "status": "Processing"}, 0) is None


def test_deposit_late_evening_keeps_local_day():
    # 2026-11-01T02:30:00Z == 2026-10-31 23:30 local
    rec = {**DEPOSIT, "insertTime": 1793500200000}
    assert deposit_row(rec, RATE)["date"] == "2026-10-31"
    assert local_day(1793500200000) == "2026-10-31"
    assert local_day("2026-11-01 02:30:00") == "2026-10-31"


def test_fiat_rows_signs():
    d = fiat_row(FIAT_DEPOSIT, 0)
    assert d["id"] == "binance:fiat:FAKEORDER0001"
    assert d["amount"] == 990.0 and d["amount_normalized"] == 990.0
    assert d["description"] == "Binance BRL deposit"
    assert d["currency"] == "BRL" and d["type"] == "CREDIT"
    assert set(d) == TX_KEYS
    w = fiat_row(FIAT_DEPOSIT, 1)
    assert w["amount"] == -990.0 and w["amount_normalized"] == -990.0
    assert w["description"] == "Binance BRL withdrawal"
    assert w["type"] == "DEBIT"


def test_earn_rows_sum_per_month_and_asset_at_daily_rates():
    rate = lambda a, d: {"2026-10-01": 5.0, "2026-10-02": 6.0}[d]
    rows = earn_rows([REWARD_D1, REWARD_D2], [], rate)
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == "binance:earn:2026-10:USDT"
    assert abs(r["amount"] - 0.2) < 1e-9
    assert r["amount_normalized"] == 1.1
    assert r["description"] == "Binance Earn interest USDT 2026-10"
    assert r["date"] == "2026-10-02"
    assert set(r) == TX_KEYS


def test_earn_distributions_grouped_with_rewards():
    rows = earn_rows([], [AIRDROP, {**AIRDROP, "asset": "USDT", "amount": "1"}], RATE)
    assert {r["id"] for r in rows} == {"binance:earn:2026-10:BNB", "binance:earn:2026-10:USDT"}


def test_earn_row_without_price_is_zero():
    rec = {**REWARD_D1, "asset": "OPN"}
    r = earn_rows([rec], [], lambda a, d: None)[0]
    assert r["amount_normalized"] == 0.0
    assert r["amount"] == 0.1
    assert is_unpriced(r)


def test_earn_row_mixed_days_sums_priced_only():
    day1 = {**REWARD_D1, "asset": "OPN", "rewards": "2", "time": 1_790_823_600_000}
    day2 = {**REWARD_D1, "asset": "OPN", "rewards": "3", "time": 1_790_823_600_000 + 86_400_000}
    rate = lambda a, d: 10.0 if d == "2026-10-02" else None
    missing = Counter()
    r = earn_rows([day1, day2], [], rate, missing)[0]
    assert r["amount_normalized"] == 30.0 and r["amount"] == 5.0
    assert not is_unpriced(r) and missing == {"OPN": 1}


def test_binance_norm_stored_with_6_dp():
    r = earn_rows([{**REWARD_D1, "rewards": "0.0000123"}], [], lambda a, d: 3.333333)[0]
    assert r["amount_normalized"] == round(0.0000123 * 3.333333, 6) != 0


def test_is_unpriced_predicate():
    assert is_unpriced({"amount": 1.0, "amount_normalized": 0.0})
    assert not is_unpriced({"amount": 1.0, "amount_normalized": 0.000001})
    assert not is_unpriced({"amount": 0.0, "amount_normalized": 0.0})


def test_mask_address():
    assert mask_address("0xFAKE000000000000000000000000000000009001") == "…9001"


def test_account_and_item_rows():
    a = account_row(123.4)
    assert a["id"] == "binance" and a["item_id"] == "binance"
    assert a["type"] == "BANK" and a["subtype"] == "BINANCE"
    assert a["role"] == "investment" and a["balance"] == 123.4
    i = item_row("2026-11-01T00:00:00Z")
    assert i["id"] == "binance" and i["status"] == "UPDATED" and i["raw_json"] == "{}"
