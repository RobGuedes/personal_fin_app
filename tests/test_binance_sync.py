import copy
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
import respx

from binance_samples import AIRDROP, DEPOSIT, FIAT_DEPOSIT, REWARD_D1, REWARD_D2, WITHDRAWAL
from finance.aggregate import binance_holdings
from finance.binance_client import BinanceClient, UnsafeKeyError
from finance.binance_sync import DAY_MS, ENDPOINTS, fetch_windowed, sync_binance, time_windows
from finance.config import Settings
from finance.db import connect

BASE = "https://api.binance.com"


def make_client() -> BinanceClient:
    s = Settings(pluggy_client_id="", pluggy_client_secret="", binance_api_key="key-1",
                 binance_api_secret="test-secret")
    return BinanceClient(s, http=httpx.Client(base_url=BASE), sleep=lambda _s: None)


def _q(call) -> dict:
    return dict(parse_qsl(urlsplit(str(call.request.url)).query))


def test_time_windows_contiguous():
    wins = time_windows(0, 100 * DAY_MS, 30)
    assert wins[0][1] == 100 * DAY_MS and wins[-1][0] == 0
    for (lo, _hi), (_lo2, hi2) in zip(wins, wins[1:], strict=False):
        assert hi2 == lo - 1
    assert all(hi - lo <= 30 * DAY_MS for lo, hi in wins)


def test_endpoint_set_excludes_bonus():
    assert set(ENDPOINTS) == {"deposits", "withdrawals", "fiat_deposits", "fiat_withdrawals",
                              "earn_rewards_realtime", "earn_rewards_locked", "distributions"}
    assert all(s.params.get("type") != "BONUS" for s in ENDPOINTS.values())
    assert ENDPOINTS["fiat_deposits"].min_interval_s == 60
    assert ENDPOINTS["fiat_withdrawals"].params == {"transactionType": 1}
    assert ENDPOINTS["earn_rewards_realtime"].params == {"type": "REALTIME"}
    assert ENDPOINTS["distributions"].paging == "none" and ENDPOINTS["distributions"].max_days == 180


@respx.mock
def test_split_when_full_window():
    respx.get(f"{BASE}/api/v3/time").respond(json={"serverTime": 1_700_000_000_000})
    full = [{"id": i} for i in range(500)]
    route = respx.get(f"{BASE}/sapi/v1/asset/assetDividend").mock(side_effect=[
        httpx.Response(200, json={"rows": full}),
        httpx.Response(200, json={"rows": [{"id": 1000 + i} for i in range(10)]}),
        httpx.Response(200, json={"rows": [{"id": 2000 + i} for i in range(10)]}),
    ])
    recs = fetch_windowed(make_client(), ENDPOINTS["distributions"], 0, 10 * DAY_MS)
    assert len(recs) == 20  # full window discarded, re-queried as two halves
    assert route.call_count == 3


@respx.mock
def test_offset_paging():
    respx.get(f"{BASE}/api/v3/time").respond(json={"serverTime": 1_700_000_000_000})
    route = respx.get(f"{BASE}/sapi/v1/capital/deposit/hisrec").mock(side_effect=[
        httpx.Response(200, json=[{"i": n} for n in range(1000)]),
        httpx.Response(200, json=[{"i": n} for n in range(3)]),
    ])
    recs = fetch_windowed(make_client(), ENDPOINTS["deposits"], 0, 10 * DAY_MS)
    assert len(recs) == 1003
    assert [_q(c)["offset"] for c in route.calls] == ["0", "1000"]


def test_fiat_calls_are_paced():
    class Fake:
        def __init__(self):
            self.n = 0

        def get(self, path, params):
            self.n += 1
            return {"data": []}

    sleeps: list[float] = []
    fetch_windowed(Fake(), ENDPOINTS["fiat_deposits"], 0, 70 * DAY_MS,
                   sleep=sleeps.append, clock=lambda: 1000.0)
    assert len(sleeps) == 2 and all(abs(s - 60) < 1e-6 for s in sleeps)


def test_fiat_pacing_shared_across_specs():
    class Fake:
        def get(self, path, params):
            return {"data": []}

    sleeps: list[float] = []
    pacer: dict[str, float] = {}
    kw = dict(sleep=sleeps.append, clock=lambda: 1000.0, pacer=pacer)
    fetch_windowed(Fake(), ENDPOINTS["fiat_deposits"], 0, 20 * DAY_MS, **kw)
    assert sleeps == []
    fetch_windowed(Fake(), ENDPOINTS["fiat_withdrawals"], 0, 20 * DAY_MS, **kw)
    assert len(sleeps) == 1 and abs(sleeps[0] - 60) < 1e-6


# --- sync_binance ----------------------------------------------------------

NOW_MS = 1_793_500_000_000  # 2026-11-01T02:26Z = 2026-10-31 local
WRITE_PERMS = ["enableWithdrawals", "enableInternalTransfer", "permitsUniversalTransfer",
               "enableSpotAndMarginTrading", "enableFutures", "enableMargin",
               "enableVanillaOptions", "enablePortfolioMarginTrading", "enableFixApiTrade"]
CLOSES = {"USDTBRL": 5.0, "BNBBRL": 3000.0}


def _ms(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).timestamp() * 1000)


def ranged(recs, when, start="startTime", end="endTime", key=None):
    def handler(request):
        q = _q_url(request.url)
        lo, hi = int(q[start]), int(q[end])
        hits = [r for r in recs if lo <= when(r) <= hi]
        return httpx.Response(200, json=hits if key is None else {key: hits})
    return handler


def _q_url(url) -> dict:
    return dict(parse_qsl(urlsplit(str(url)).query))


def klines_handler(available, listed_from=None):
    listed_from = listed_from or {}

    def handler(request):
        q = _q_url(request.url)
        symbol = q["symbol"]
        if symbol not in available:
            return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})
        t, rows = int(q["startTime"]), []
        while t <= int(q["endTime"]):
            if t >= listed_from.get(symbol, 0):
                rows.append([t, "0", "0", "0", str(available[symbol]), "0"])
            t += DAY_MS
        return httpx.Response(200, json=rows)
    return handler


class Env:
    def __init__(self, restrictions=None, spot=None, flexible=None, locked=None, funding="0.001"):
        self.deposits = [copy.deepcopy(DEPOSIT)]
        self.withdrawals = [copy.deepcopy(WITHDRAWAL)]
        self.fiat = [copy.deepcopy(FIAT_DEPOSIT)]
        self.fiat_out = [{**FIAT_DEPOSIT, "orderNo": "FAKEORDER0002", "amount": "200.00"}]
        self.rewards = [copy.deepcopy(REWARD_D1)]
        self.dists = [copy.deepcopy(AIRDROP)]
        self.available = dict(CLOSES)
        self.listed_from = {}
        self.restrictions = restrictions or {k: False for k in WRITE_PERMS} | {"ipRestrict": True}
        self.spot = spot if spot is not None else [
            {"asset": "LDUSDT", "free": "4321.09000000", "locked": "0.00000000"},
            {"asset": "BNB", "free": "1.5", "locked": "0.5"},
        ]
        self.flexible = flexible if flexible is not None else [
            {"asset": "USDT", "totalAmount": "4321.09", "productId": "USDT001"}]
        self.locked = locked if locked is not None else []
        self.funding = funding

    def mount(self, mock):
        mock.get(f"{BASE}/api/v3/time").respond(json={"serverTime": NOW_MS})
        mock.get(f"{BASE}/sapi/v1/account/apiRestrictions").mock(
            side_effect=lambda r: httpx.Response(200, json=self.restrictions))
        self.dep_route = mock.get(f"{BASE}/sapi/v1/capital/deposit/hisrec").mock(
            side_effect=lambda r: ranged(self.deposits, lambda d: d["insertTime"])(r))
        mock.get(f"{BASE}/sapi/v1/capital/withdraw/history").mock(
            side_effect=lambda r: ranged(self.withdrawals, lambda d: _ms(d["applyTime"]))(r))
        self.fiat_route = mock.get(f"{BASE}/sapi/v1/fiat/orders").mock(
            side_effect=lambda r: ranged(
                self.fiat if _q_url(r.url)["transactionType"] == "0" else self.fiat_out,
                lambda d: d["createTime"], "beginTime", "endTime", "data")(r))
        mock.get(f"{BASE}/sapi/v1/simple-earn/flexible/history/rewardsRecord").mock(
            side_effect=lambda r: ranged(self.rewards, lambda d: d["time"], key="rows")(r))
        mock.get(f"{BASE}/sapi/v1/simple-earn/locked/history/rewardsRecord").mock(
            side_effect=lambda r: ranged([], lambda d: d["time"], key="rows")(r))
        mock.get(f"{BASE}/sapi/v1/asset/assetDividend").mock(
            side_effect=lambda r: ranged(self.dists, lambda d: d["divTime"], key="rows")(r))
        mock.get(f"{BASE}/api/v3/account").mock(
            side_effect=lambda r: httpx.Response(200, json={"balances": self.spot}))
        mock.get(f"{BASE}/sapi/v1/simple-earn/flexible/position").mock(
            side_effect=lambda r: httpx.Response(200, json={"total": 1, "rows": self.flexible}))
        mock.get(f"{BASE}/sapi/v1/simple-earn/locked/position").mock(
            side_effect=lambda r: httpx.Response(200, json={"total": 0, "rows": self.locked}))
        mock.get(f"{BASE}/sapi/v1/asset/wallet/balance").mock(
            side_effect=lambda r: httpx.Response(200, json=[
                {"activate": True, "balance": "0.5", "walletName": "Spot"},
                {"activate": True, "balance": self.funding, "walletName": "Funding"}]))
        mock.get(f"{BASE}/api/v3/klines").mock(
            side_effect=lambda r: klines_handler(self.available, self.listed_from)(r))


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    yield c
    c.close()


def run(conn, window_days=30):
    return sync_binance(conn, make_client(), window_days=window_days, now_ms=NOW_MS,
                        sleep=lambda _s: None, clock=lambda: 0.0)


def n_rows(conn):
    return conn.execute("SELECT COUNT(*) FROM transactions WHERE account_id = 'binance'").fetchone()[0]


@respx.mock
def test_first_sync_inserts_rows_and_account(conn):
    Env().mount(respx)
    r = run(conn)
    ids = {x[0] for x in conn.execute("SELECT id FROM transactions")}
    assert ids == {"binance:dep:FAKEDEP0000000001", "binance:wd:FAKEWD0000000000000000000000001",
                   "binance:fiat:FAKEORDER0001", "binance:fiat:FAKEORDER0002", "binance:earn:2026-10:USDT", "binance:earn:2026-10:BNB"}
    assert (r.inserted, r.updated, r.unchanged) == (6, 0, 0)
    amt = {x[0]: x[1] for x in conn.execute("SELECT id, amount_normalized FROM transactions")}
    assert amt["binance:fiat:FAKEORDER0001"] > 0 and amt["binance:fiat:FAKEORDER0002"] < 0
    assert r.ip_restricted is True
    acc = conn.execute("SELECT role, balance FROM accounts WHERE id = 'binance'").fetchone()
    assert acc["role"] == "investment" and acc["balance"] == pytest.approx(r.positions_brl)
    assert conn.execute("SELECT COUNT(*) FROM items WHERE id = 'binance'").fetchone()[0] == 1


@respx.mock
def test_resync_is_idempotent(conn):
    Env().mount(respx)
    run(conn)
    first_seen = conn.execute("SELECT first_seen_at FROM transactions ORDER BY id").fetchall()
    r = run(conn, window_days=200)  # sample records are up to ~118 days old
    assert (r.inserted, r.updated) == (0, 0) and r.unchanged == 6
    assert conn.execute("SELECT first_seen_at FROM transactions ORDER BY id").fetchall() == first_seen
    assert n_rows(conn) == 6


@respx.mock
def test_trailing_window_after_first_run(conn):
    env = Env()
    env.mount(respx)
    run(conn)
    first_start = min(int(_q(c)["startTime"]) for c in env.dep_route.calls)
    assert abs(first_start - (NOW_MS - 540 * DAY_MS)) < 5 * 60_000
    n = len(env.dep_route.calls)
    run(conn)
    starts = [int(_q(c)["startTime"]) for c in list(env.dep_route.calls)[n:]]
    assert abs(min(starts) - (NOW_MS - 30 * DAY_MS)) < 5 * 60_000


@respx.mock
def test_price_backfill_updates_zero_rows(conn):
    env = Env()
    env.deposits = [{**DEPOSIT, "coin": "OPN", "id": "FAKEDEP0000000002", "amount": "100"}]
    env.mount(respx)
    r1 = run(conn)
    row = conn.execute("SELECT amount_normalized FROM transactions WHERE id = 'binance:dep:FAKEDEP0000000002'").fetchone()
    assert row[0] == 0.0 and "no price for OPN" in r1.warnings
    env.available["OPNUSDT"] = 0.5
    r2 = run(conn)  # default window: the deposit is older than 30 days
    row = conn.execute("SELECT amount_normalized FROM transactions WHERE id = 'binance:dep:FAKEDEP0000000002'").fetchone()
    assert row[0] == pytest.approx(100 * 0.5 * 5.0)
    assert r2.updated == 1 and r2.inserted == 0
    assert "no price for OPN" not in r2.warnings


@respx.mock
def test_role_is_not_overwritten(conn):
    Env().mount(respx)
    run(conn)
    conn.execute("UPDATE accounts SET role = 'other' WHERE id = 'binance'")
    conn.commit()
    run(conn)
    assert conn.execute("SELECT role FROM accounts WHERE id = 'binance'").fetchone()[0] == "other"


@respx.mock
def test_positions_exclude_ld_mirrors(conn):
    Env().mount(respx)
    r = run(conn)
    pos = {(x["wallet"], x["asset"]): x for x in conn.execute("SELECT * FROM binance_positions")}
    assert ("spot", "LDUSDT") not in pos
    assert pos[("spot", "BNB")]["amount"] == 2.0 and pos[("spot", "BNB")]["brl_value"] == 6000.0
    assert pos[("earn_flexible", "USDT")]["amount"] == 4321.09
    assert pos[("earn_flexible", "USDT")]["brl_value"] == pytest.approx(4321.09 * 5.0)
    assert pos[("funding", "BTC")]["brl_value"] is None  # no BTCBRL price in the mock
    total = sum(x["brl_value"] or 0 for x in pos.values())
    assert r.positions_brl == pytest.approx(total)
    assert conn.execute("SELECT balance FROM accounts WHERE id = 'binance'").fetchone()[0] == pytest.approx(total)
    h = binance_holdings(conn)
    assert h["total_brl"] == pytest.approx(total)
    assert h["by_asset"][0][0] == "USDT"


def test_holdings_none_without_snapshot(conn):
    assert binance_holdings(conn) is None


@respx.mock
def test_pluggy_rows_untouched(conn):
    conn.execute("INSERT INTO items (id, raw_json) VALUES ('item-1', '{}')")
    conn.execute("INSERT INTO accounts (id, item_id, type, subtype, name, raw_json) "
                 "VALUES ('acc-1', 'item-1', 'BANK', 'CHECKING_ACCOUNT', 'x', '{}')")
    conn.execute("INSERT INTO transactions (id, account_id, date, amount, amount_normalized, payment_method, raw_json, "
                 "first_seen_at, updated_at) VALUES ('p1', 'acc-1', '2026-10-01', -5, -5, 'pix', '{}', 'a', 'b')")
    conn.commit()
    before = [tuple(x) for x in conn.execute("SELECT * FROM transactions WHERE id = 'p1'")]
    Env().mount(respx)
    run(conn)
    assert [tuple(x) for x in conn.execute("SELECT * FROM transactions WHERE id = 'p1'")] == before
    assert conn.execute("SELECT COUNT(*) FROM accounts WHERE id = 'acc-1'").fetchone()[0] == 1


@respx.mock
def test_unsafe_key_aborts_before_writes(conn):
    env = Env(restrictions={k: False for k in WRITE_PERMS} | {"enableWithdrawals": True})
    env.mount(respx)
    with pytest.raises(UnsafeKeyError):
        run(conn)
    assert n_rows(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM accounts WHERE id = 'binance'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM binance_positions").fetchone()[0] == 0


OPN = [{**REWARD_D1, "asset": "OPN"}, {**REWARD_D2, "asset": "OPN"}]  # local days 2026-10-01 and 10-02


@respx.mock
def test_partially_priced_earn_month_warns_per_asset_and_values_priced_days(conn):
    env = Env()
    env.rewards = [*OPN, REWARD_D1]
    env.available["OPNUSDT"] = 0.5
    env.listed_from["OPNUSDT"] = _ms("2026-10-02 03:00:00")  # no candle for 10-01 local
    env.mount(respx)
    r = run(conn)
    assert "no price for OPN on 1 day" in r.warnings
    assert not any("USDT on" in w for w in r.warnings)
    row = conn.execute("SELECT amount, amount_normalized FROM transactions "
                       "WHERE id = 'binance:earn:2026-10:OPN'").fetchone()
    assert row["amount"] == pytest.approx(0.2)
    assert row["amount_normalized"] == pytest.approx(0.1 * 0.5 * 5.0)  # 10-02 only


@respx.mock
def test_zero_earn_row_backfill_prices_every_item_day(conn):
    from finance import binance_normalize as bn
    from finance.binance_normalize import earn_rows
    from finance.binance_sync import upsert_row
    from finance.sync import _upsert
    items = [{**REWARD_D1, "asset": "OPN", "time": _ms("2026-08-30 15:00:00")},
             {**REWARD_D1, "asset": "OPN", "time": _ms("2026-08-31 15:00:00")}]
    with conn:
        _upsert(conn, "items", bn.item_row("2026-09-01T00:00:00+00:00"))
        _upsert(conn, "accounts", bn.account_row(None))
        for row in earn_rows(items, [], lambda a, d: None):
            upsert_row(conn, row, "2026-09-01T00:00:00+00:00")
    env = Env()
    env.rewards = []
    env.available["OPNUSDT"] = 0.5
    env.mount(respx)
    run(conn)  # both item days are outside the 30-day fetch window
    row = conn.execute("SELECT amount_normalized FROM transactions "
                       "WHERE id = 'binance:earn:2026-08:OPN'").fetchone()
    assert row[0] == pytest.approx(2 * 0.1 * 0.5 * 5.0)


@respx.mock
def test_gap_between_syncs_longer_than_window_is_backfilled(conn):
    """Not syncing for 50 days must not lose a deposit made in between (e.g. Cliente Exterior income)."""
    env = Env()
    env.mount(respx)
    run(conn)
    env.deposits.append({**copy.deepcopy(env.deposits[0]), "id": "FAKEDEP0000000GAP",
                         "insertTime": NOW_MS + 10 * DAY_MS})
    sync_binance(conn, make_client(), window_days=30, now_ms=NOW_MS + 50 * DAY_MS,
                 sleep=lambda _s: None, clock=lambda: 0.0)
    ids = {x[0] for x in conn.execute("SELECT id FROM transactions")}
    assert "binance:dep:FAKEDEP0000000GAP" in ids


@respx.mock
def test_row_priced_at_a_partial_close_is_repriced(conn):
    """A deposit made today is priced at today's partial close; the next sync re-fetches that close
    (fx replaces the last stored one), so the row must follow it instead of keeping the intraday value."""
    env = Env()
    env.deposits = [{**DEPOSIT, "id": "FAKEDEP0000000TDY", "amount": "100", "insertTime": NOW_MS - 3600_000}]
    env.mount(respx)
    run(conn)
    row_id = "binance:dep:FAKEDEP0000000TDY"
    assert conn.execute("SELECT amount_normalized FROM transactions WHERE id = ?", (row_id,)).fetchone()[0] == 500
    env.available["USDTBRL"] = 5.5  # the day's real close
    r = run(conn)
    assert conn.execute("SELECT amount_normalized FROM transactions WHERE id = ?", (row_id,)).fetchone()[0] == 550
    assert r.updated >= 1


@respx.mock
def test_priced_row_is_not_overwritten_by_a_missing_price(conn):
    env = Env()
    env.deposits = [{**DEPOSIT, "id": "FAKEDEP0000000TDY", "amount": "100", "insertTime": NOW_MS - 3600_000}]
    env.mount(respx)
    run(conn)
    del env.available["USDTBRL"]
    run(conn)
    row = conn.execute("SELECT amount_normalized FROM transactions WHERE id = 'binance:dep:FAKEDEP0000000TDY'")
    assert row.fetchone()[0] == 500
