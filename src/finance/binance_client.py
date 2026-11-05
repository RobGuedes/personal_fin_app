"""Read-only Binance API client: HMAC-SHA256 signed GETs, server-clock sync, backoff.

Only GET requests are ever sent, and `check_read_only()` refuses keys that can trade, withdraw
or transfer. Docs: https://developers.binance.com/docs/ (SIGNED = USER_DATA endpoints).
"""

import hashlib
import hmac
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from finance.config import Settings

MAX_RETRIES = 5
RECV_WINDOW_MS = 10_000
DAY_MS = 86_400_000
KLINES_LIMIT = 1000
LOCAL_TZ = timezone(timedelta(hours=-3))  # America/Sao_Paulo, no DST since 2019

# Permissions that must all be False for the key to be accepted.
WRITE_PERMISSIONS = (
    "enableWithdrawals",
    "enableInternalTransfer",
    "permitsUniversalTransfer",
    "enableSpotAndMarginTrading",
    "enableFutures",
    "enableMargin",
    "enableVanillaOptions",
    "enablePortfolioMarginTrading",
    "enableFixApiTrade",
)


class BinanceError(RuntimeError):
    pass


class UnsafeKeyError(BinanceError):
    pass


class UnknownSymbolError(BinanceError):
    pass


class BinanceClient:
    def __init__(
        self,
        settings: Settings,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not settings.binance_api_key or not settings.binance_api_secret.get_secret_value():
            raise BinanceError("BINANCE_API_KEY / BINANCE_API_SECRET are not set in .env")
        self._key = settings.binance_api_key
        self._secret = settings.binance_api_secret.get_secret_value().encode()
        self._http = http or httpx.Client(base_url=settings.binance_base_url, timeout=60)
        self._sleep = sleep
        self._offset_ms: int | None = None

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "BinanceClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- transport --------------------------------------------------------

    def _sync_clock(self) -> int:
        resp = self._http.get("/api/v3/time")
        if resp.status_code != 200:
            raise BinanceError(f"GET /api/v3/time: HTTP {resp.status_code}")
        self._offset_ms = int(resp.json()["serverTime"]) - int(time.time() * 1000)
        return self._offset_ms

    def _signed_url(self, path: str, params: dict[str, Any]) -> str:
        offset = self._sync_clock() if self._offset_ms is None else self._offset_ms
        query = urlencode({
            **{k: v for k, v in params.items() if v is not None},
            "recvWindow": RECV_WINDOW_MS,
            "timestamp": int(time.time() * 1000) + offset,
        })
        sig = hmac.new(self._secret, query.encode(), hashlib.sha256).hexdigest()
        return f"{path}?{query}&signature={sig}"

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Signed GET. Retries on 429 / 5xx / clock drift; a 418 (IP ban) stops immediately."""
        return self._request(path, lambda: self._signed_url(path, params or {}), {"X-MBX-APIKEY": self._key})

    def _request(self, path: str, url: Callable[[], str], headers: dict[str, str]) -> Any:
        """GET with the shared retry policy. `url` is rebuilt per attempt (signed URLs change on resync)."""
        resynced = False
        for attempt in range(MAX_RETRIES):
            resp = self._http.get(url(), headers=headers)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 418:
                raise BinanceError(f"GET {path}: HTTP 418 (IP banned for {resp.headers.get('Retry-After')}s)")
            if resp.status_code == 429:
                self._sleep(float(resp.headers.get("Retry-After") or 60))
                continue
            if resp.status_code >= 500:
                self._sleep(2**attempt)
                continue
            code, msg = _error(resp)
            if code == -1021 and not resynced:  # timestamp outside recvWindow
                self._offset_ms = None
                resynced = True
                continue
            if code == -1121:
                raise UnknownSymbolError(f"GET {path}: unknown symbol")
            raise BinanceError(f"GET {path}: HTTP {resp.status_code} code={code} {msg}")
        raise BinanceError(f"GET {path}: gave up after {MAX_RETRIES} attempts")

    # --- public market data -----------------------------------------------

    def klines(self, symbol: str, start_ms: int, end_ms: int) -> list[tuple[str, float]]:
        """Unsigned daily closes as [(local date 'YYYY-MM-DD' at UTC-3, close)], oldest first."""
        rows_out: list[tuple[str, float]] = []
        start = start_ms
        while True:
            params = {
                "symbol": symbol, "interval": "1d", "timeZone": "-3",
                "startTime": start, "endTime": end_ms, "limit": KLINES_LIMIT,
            }
            url = f"/api/v3/klines?{urlencode(params)}"

            def klines_url(url: str = url) -> str:  # public endpoint: unsigned, the same URL every attempt
                return url

            rows = self._request("/api/v3/klines", klines_url, {})
            for row in rows:
                day = datetime.fromtimestamp(int(row[0]) / 1000, tz=LOCAL_TZ).date().isoformat()
                rows_out.append((day, float(row[4])))
            if not rows or len(rows) < KLINES_LIMIT or int(rows[-1][0]) >= end_ms:
                return rows_out
            start = int(rows[-1][0]) + DAY_MS

    # --- safety -----------------------------------------------------------

    def check_read_only(self) -> dict:
        """Return the key's restrictions; raise UnsafeKeyError if any write permission is on."""
        r = self.get("/sapi/v1/account/apiRestrictions")
        enabled = [p for p in WRITE_PERMISSIONS if r.get(p)]
        if enabled:
            raise UnsafeKeyError(
                "Refusing to use this API key: it has write permissions enabled "
                f"({', '.join(enabled)}). Create a key with only 'Enable Reading'."
            )
        return r


def _error(resp: httpx.Response) -> tuple[int | None, str]:
    try:
        body = resp.json()
        return body.get("code"), str(body.get("msg", ""))[:200]
    except ValueError:
        return None, resp.text[:200]
