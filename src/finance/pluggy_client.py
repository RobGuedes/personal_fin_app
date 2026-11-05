"""Read-only Pluggy API client: auth, paginated GETs, retry/backoff.

Endpoints (docs.pluggy.ai):
- POST /auth                      -> {"apiKey"}, valid ~2h, sent as X-API-KEY
- GET  /items/{id}
- GET  /accounts?itemId=          page-based
- GET  /v2/transactions?accountId= cursor-based ("next" query string)
- GET  /investments?itemId=       page-based
- GET  /bills?accountId=          page-based (credit cards only)
- GET  /identity?itemId=
"""

import time
from collections.abc import Callable, Iterator
from datetime import date
from typing import Any
from urllib.parse import parse_qs

import httpx

from finance.config import Settings

MAX_RETRIES = 5
MAX_RATE_LIMIT_WAIT_S = 120.0  # a bogus/huge RateLimit-Reset must not stall the sync for hours


class PluggyError(RuntimeError):
    pass


def _error_code(resp: httpx.Response) -> str:
    """Pluggy's short error code (e.g. ' (ITEM_NOT_FOUND)') if the body has one; nothing else from the body."""
    try:
        code = resp.json().get("codeDescription") or resp.json().get("code")
    except Exception:
        return ""
    return f" ({code})" if isinstance(code, str) and code.replace("_", "").isalnum() and len(code) <= 60 else ""


class PluggyClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._settings = settings
        self._sleep = sleep
        self._http = http or httpx.Client(base_url=settings.pluggy_base_url, timeout=60)
        self._api_key: str | None = None

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "PluggyClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- auth / transport -------------------------------------------------

    def _authenticate(self) -> str:
        resp = self._http.post(
            "/auth",
            json={
                "clientId": self._settings.pluggy_client_id,
                "clientSecret": self._settings.pluggy_client_secret.get_secret_value(),
            },
        )
        if resp.status_code != 200:
            raise PluggyError(f"auth failed: HTTP {resp.status_code}")
        self._api_key = resp.json()["apiKey"]
        return self._api_key

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        reauthed = False
        for attempt in range(MAX_RETRIES):
            key = self._api_key or self._authenticate()
            resp = self._http.get(path, params=params, headers={"X-API-KEY": key})
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (401, 403) and not reauthed:
                self._api_key = None
                reauthed = True
                continue
            if resp.status_code == 429:
                wait = float(resp.headers.get("RateLimit-Reset") or resp.headers.get("Retry-After") or 60)
                self._sleep(min(wait, MAX_RATE_LIMIT_WAIT_S))
                continue
            if resp.status_code >= 500:
                self._sleep(2.0**attempt)
                continue
            # Never the body: error text reaches the UI and sync_runs, and a body could echo account data.
            raise PluggyError(f"GET {path}: HTTP {resp.status_code}{_error_code(resp)}")
        raise PluggyError(f"GET {path}: gave up after {MAX_RETRIES} attempts")

    def _paged(self, path: str, params: dict[str, Any]) -> list[dict]:
        results: list[dict] = []
        page = 1
        while True:
            body = self._get(path, {**params, "page": page, "pageSize": 500})
            results.extend(body.get("results", []))
            if page >= body.get("totalPages", 1):
                return results
            page += 1

    # --- resources --------------------------------------------------------

    def get_item(self, item_id: str) -> dict:
        return self._get(f"/items/{item_id}")

    def list_accounts(self, item_id: str) -> list[dict]:
        return self._paged("/accounts", {"itemId": item_id})

    def list_investments(self, item_id: str) -> list[dict]:
        return self._paged("/investments", {"itemId": item_id})

    def list_bills(self, account_id: str) -> list[dict]:
        return self._paged("/bills", {"accountId": account_id})

    def get_identity(self, item_id: str) -> dict | None:
        try:
            return self._get("/identity", {"itemId": item_id})
        except PluggyError:
            return None

    def iter_transactions(
        self, account_id: str, date_from: date | None = None, date_to: date | None = None
    ) -> Iterator[dict]:
        params: dict[str, Any] = {"accountId": account_id}
        if date_from:
            params["dateFrom"] = date_from.isoformat()
        if date_to:
            params["dateTo"] = date_to.isoformat()
        seen: set[str] = set()
        while True:
            body = self._get("/v2/transactions", params)
            yield from body.get("results", [])
            nxt = body.get("next")
            if not nxt:
                return
            after = parse_qs(nxt.lstrip("?")).get("after")
            if not after:
                return
            if after[0] in seen:  # the API handed back a cursor we already followed: stop, don't spin forever
                raise PluggyError("GET /v2/transactions: repeated cursor")
            seen.add(after[0])
            params = {**params, "after": after[0]}
