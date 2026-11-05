import hashlib
import hmac
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
import respx

from finance.binance_client import BinanceClient, BinanceError, UnknownSymbolError, UnsafeKeyError
from finance.config import Settings

BASE = "https://api.binance.com"
SECRET = "test-secret"


def make_client() -> BinanceClient:
    s = Settings(pluggy_client_id="", pluggy_client_secret="", binance_api_key="key-1",
                 binance_api_secret=SECRET)
    return BinanceClient(s, http=httpx.Client(base_url=BASE), sleep=lambda _s: None)


def mock_time(server_ms: int = 1_700_000_000_000):
    return respx.get(f"{BASE}/api/v3/time").respond(json={"serverTime": server_ms})


@respx.mock
def test_signed_get_sends_key_header_and_valid_signature():
    mock_time()
    route = respx.get(f"{BASE}/sapi/v1/capital/deposit/hisrec").respond(json=[{"amount": "1"}])
    assert make_client().get("/sapi/v1/capital/deposit/hisrec", {"startTime": 1, "endTime": 2}) == [{"amount": "1"}]
    req = route.calls[0].request
    assert req.headers["X-MBX-APIKEY"] == "key-1"
    query = urlsplit(str(req.url)).query
    unsigned, sig = query.rsplit("&signature=", 1)
    assert sig == hmac.new(SECRET.encode(), unsigned.encode(), hashlib.sha256).hexdigest()
    params = dict(parse_qsl(unsigned))
    assert params["startTime"] == "1" and "timestamp" in params and "recvWindow" in params


@respx.mock
def test_timestamp_uses_server_clock_offset():
    mock_time(server_ms=5_000_000_000_000)  # far in the future vs local clock
    route = respx.get(f"{BASE}/api/v3/account").respond(json={})
    make_client().get("/api/v3/account")
    ts = int(dict(parse_qsl(urlsplit(str(route.calls[0].request.url)).query))["timestamp"])
    assert abs(ts - 5_000_000_000_000) < 60_000


@respx.mock
def test_retries_after_429():
    mock_time()
    route = respx.get(f"{BASE}/api/v3/account")
    route.side_effect = [httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(200, json={"ok": 1})]
    assert make_client().get("/api/v3/account") == {"ok": 1}


@respx.mock
def test_418_ban_raises_immediately():
    mock_time()
    route = respx.get(f"{BASE}/api/v3/account").respond(418, headers={"Retry-After": "120"})
    with pytest.raises(BinanceError, match="418"):
        make_client().get("/api/v3/account")
    assert route.call_count == 1


@respx.mock
def test_error_body_is_reported_without_secret():
    mock_time()
    respx.get(f"{BASE}/sapi/v1/pay/transactions").respond(400, json={"code": -1102, "msg": "bad param"})
    with pytest.raises(BinanceError) as exc:
        make_client().get("/sapi/v1/pay/transactions")
    assert "-1102" in str(exc.value) and SECRET not in str(exc.value)


@respx.mock
def test_refuses_key_with_write_permissions():
    mock_time()
    respx.get(f"{BASE}/sapi/v1/account/apiRestrictions").respond(
        json={"enableReading": True, "enableWithdrawals": True, "enableSpotAndMarginTrading": False})
    with pytest.raises(UnsafeKeyError, match="enableWithdrawals"):
        make_client().check_read_only()


@respx.mock
def test_accepts_read_only_key():
    mock_time()
    respx.get(f"{BASE}/sapi/v1/account/apiRestrictions").respond(
        json={"ipRestrict": True, "enableReading": True, "enableWithdrawals": False,
              "enableInternalTransfer": False, "permitsUniversalTransfer": False,
              "enableSpotAndMarginTrading": False, "enableFutures": False, "enableMargin": False,
              "enableVanillaOptions": False, "enablePortfolioMarginTrading": False,
              "enableFixApiTrade": False, "enableFixReadOnly": False})
    assert make_client().check_read_only()["ipRestrict"] is True


def test_missing_credentials_raise():
    s = Settings(pluggy_client_id="", pluggy_client_secret="")
    with pytest.raises(BinanceError, match="BINANCE_API_KEY"):
        BinanceClient(s)


@respx.mock
def test_klines_unsigned_local_dates():
    route = respx.get(f"{BASE}/api/v3/klines").respond(json=[
        [1_790_823_600_000, "5.30", "5.40", "5.20", "5.33", "0", 1_790_909_999_999, "0", 0, "0", "0", "0"],
    ])  # openTime = 2026-10-01 00:00 at UTC-3
    assert make_client().klines("USDTBRL", 1_790_823_600_000, 1_790_909_999_999) == [("2026-10-01", 5.33)]
    req = route.calls[0].request
    assert "signature" not in str(req.url) and "X-MBX-APIKEY" not in req.headers
    assert req.url.params["timeZone"] == "-3" and req.url.params["interval"] == "1d"


@respx.mock
def test_klines_unknown_symbol():
    respx.get(f"{BASE}/api/v3/klines").respond(400, json={"code": -1121, "msg": "Invalid symbol."})
    with pytest.raises(UnknownSymbolError):
        make_client().klines("OPNBRL", 0, 1)


@respx.mock
def test_klines_pages_from_last_open_time_plus_one_day():
    day = 86_400_000
    start = 1_790_823_600_000
    full = [[start + i * day, "1", "1", "1", "2.5", "0", 0, "0", 0, "0", "0", "0"] for i in range(1000)]
    last = [[start + 1000 * day, "1", "1", "1", "3.5", "0", 0, "0", 0, "0", "0", "0"]]
    route = respx.get(f"{BASE}/api/v3/klines")
    route.side_effect = [httpx.Response(200, json=full), httpx.Response(200, json=last)]
    out = make_client().klines("USDTBRL", start, start + 1001 * day)
    assert len(out) == 1001 and out[-1][1] == 3.5
    assert route.calls[1].request.url.params["startTime"] == str(start + 999 * day + day)


def test_secret_not_in_settings_repr():
    s = Settings(pluggy_client_id="", pluggy_client_secret="", binance_api_key="k", binance_api_secret="s3cr3t")
    assert "s3cr3t" not in repr(s)
