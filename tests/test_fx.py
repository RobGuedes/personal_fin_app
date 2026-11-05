import httpx
import pytest
import respx

from finance.binance_client import BinanceClient
from finance.config import Settings
from finance.db import connect
from finance.fx import ensure_rates, rate, rate_fn

BASE = "https://api.binance.com"
DAY_MS = 86_400_000
D1 = 1_790_823_600_000  # 2026-10-01 00:00 UTC-3 (03:00Z)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    yield c
    c.close()


def make_client() -> BinanceClient:
    s = Settings(pluggy_client_id="", pluggy_client_secret="", binance_api_key="k",
                 binance_api_secret="s")
    return BinanceClient(s, http=httpx.Client(base_url=BASE), sleep=lambda _s: None)


def put(conn, rows):
    conn.executemany("INSERT INTO fx_rates(date, pair, close) VALUES (?,?,?)", rows)


def kl(closes):
    return [[D1 + i * DAY_MS, "0", "0", "0", str(c), "0"] for i, c in enumerate(closes)]


def test_rate_direct_and_via_usdt(conn):
    put(conn, [("2026-10-01", "USDTBRL", 5.0), ("2026-10-01", "BTCBRL", 600000),
               ("2026-10-01", "OPNUSDT", 0.5)])
    assert rate(conn, "BTC", "2026-10-01") == 600000
    assert rate(conn, "OPN", "2026-10-01") == 2.5
    assert rate(conn, "BRL", "2026-10-01") == 1.0
    assert rate_fn(conn)("OPN", "2026-10-01") == 2.5


def test_rate_falls_back_to_previous_day_within_3(conn):
    put(conn, [("2026-10-01", "BTCBRL", 600000)])
    assert rate(conn, "BTC", "2026-10-03") == 600000
    assert rate(conn, "BTC", "2026-10-05") is None


@respx.mock
def test_ensure_rates_fetches_only_missing_days(conn):
    route = respx.get(f"{BASE}/api/v3/klines").respond(json=kl([10, 11, 12]))
    client = make_client()
    assert ensure_rates(conn, client, {"BTC", "BRL"}, "2026-10-01", "2026-10-03") == []
    assert route.call_count == 1
    assert rate(conn, "BTC", "2026-10-02") == 11
    ensure_rates(conn, client, {"BTC"}, "2026-10-01", "2026-10-03")
    assert route.call_count == 2  # only the last stored day is re-requested
    assert dict(route.calls[1].request.url.params)["startTime"] == str(D1 + 2 * DAY_MS)


@respx.mock
def test_ensure_rates_only_requests_span_of_missing(conn):
    put(conn, [("2026-10-01", "BTCBRL", 10)])
    route = respx.get(f"{BASE}/api/v3/klines").respond(json=kl([10, 11, 12])[1:])
    ensure_rates(conn, make_client(), {"BTC"}, "2026-10-01", "2026-10-03")
    assert dict(route.calls[0].request.url.params)["startTime"] == str(D1)  # last stored day is refreshed


@respx.mock
def test_via_usdt_ensures_usdtbrl_and_remembers_unknown(conn):
    def side(request):
        sym = request.url.params["symbol"]
        if sym.endswith("BRL") and sym != "USDTBRL":
            return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})
        return httpx.Response(200, json=kl([5, 5]))
    route = respx.get(f"{BASE}/api/v3/klines").mock(side_effect=side)
    ensure_rates(conn, make_client(), {"AAA", "BBB"}, "2026-10-01", "2026-10-02")
    syms = [c.request.url.params["symbol"] for c in route.calls]
    assert syms.count("USDTBRL") == 1
    assert {"AAAUSDT", "BBBUSDT"} <= set(syms)
    assert rate(conn, "AAA", "2026-10-01") == 25


@respx.mock
def test_unknown_asset_has_no_price(conn):
    respx.get(f"{BASE}/api/v3/klines").respond(400, json={"code": -1121, "msg": "Invalid symbol."})
    assert ensure_rates(conn, make_client(), {"XYZ"}, "2026-10-01", "2026-10-02") == ["no price for XYZ"]
    assert rate(conn, "XYZ", "2026-10-01") is None


@respx.mock
def test_partial_last_day_close_is_replaced_next_sync(conn):
    put(conn, [("2026-10-01", "BTCBRL", 10), ("2026-10-02", "BTCBRL", 11.5)])  # 10-02 stored mid-day
    respx.get(f"{BASE}/api/v3/klines").respond(json=kl([10, 12, 13])[1:])
    ensure_rates(conn, make_client(), {"BTC"}, "2026-10-01", "2026-10-03")
    assert rate(conn, "BTC", "2026-10-02") == 12
    assert rate(conn, "BTC", "2026-10-03") == 13
    assert rate(conn, "BTC", "2026-10-01") == 10
