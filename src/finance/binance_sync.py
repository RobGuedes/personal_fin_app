"""Binance sync: windowed fetching of the read-only history endpoints."""

import json
import sqlite3
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from finance import binance_normalize as bn
from finance.binance_client import BinanceClient
from finance.fx import ensure_rates, rate_fn
from finance.sync import _upsert

DAY_MS = 86_400_000


@dataclass
class Windowed:
    """An endpoint queried in time windows, walking back from now."""
    name: str
    path: str
    max_days: int
    params: dict[str, Any] = field(default_factory=dict)
    time_params: tuple[str, str] = ("startTime", "endTime")
    paging: str = "none"            # none (split window when full) | offset | page | current
    page_size: int = 100
    size_param: str = "limit"
    max_lookback_days: int | None = None  # endpoint rejects older start times
    min_interval_s: float = 0       # minimum spacing between consecutive calls of this spec


ENDPOINTS: dict[str, Windowed] = {w.name: w for w in [
    Windowed("deposits", "/sapi/v1/capital/deposit/hisrec", 90, paging="offset", page_size=1000),
    Windowed("withdrawals", "/sapi/v1/capital/withdraw/history", 90, paging="offset", page_size=1000),
    Windowed("fiat_deposits", "/sapi/v1/fiat/orders", 30, {"transactionType": 0}, ("beginTime", "endTime"),
             "page", 500, "rows", min_interval_s=60),
    Windowed("fiat_withdrawals", "/sapi/v1/fiat/orders", 30, {"transactionType": 1}, ("beginTime", "endTime"),
             "page", 500, "rows", min_interval_s=60),
    Windowed("earn_rewards_realtime", "/sapi/v1/simple-earn/flexible/history/rewardsRecord", 30,
             {"type": "REALTIME"}, paging="current", page_size=100, size_param="size"),
    Windowed("earn_rewards_locked", "/sapi/v1/simple-earn/locked/history/rewardsRecord", 30,
             paging="current", page_size=100, size_param="size"),
    Windowed("distributions", "/sapi/v1/asset/assetDividend", 180, page_size=500),
]}


def time_windows(start_ms: int, end_ms: int, max_days: int) -> list[tuple[int, int]]:
    """Non-overlapping [start, end] windows of at most max_days, newest first."""
    wins, hi, span = [], end_ms, max_days * DAY_MS
    while hi > start_ms:
        lo = max(start_ms, hi - span)
        wins.append((lo, hi))
        hi = lo - 1
    return wins


def records_of(body: Any) -> list[dict]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("data", "rows", "list", "balances", "snapshotVos"):
            if isinstance(body.get(key), list):
                return body[key]
    return []


def fetch_windowed(client: BinanceClient, spec: Windowed, start_ms: int, end_ms: int,
                   sleep: Callable[[float], None] = time.sleep,
                   clock: Callable[[], float] = time.monotonic,
                   pacer: dict[str, float] | None = None) -> list[dict]:
    """pacer maps path -> time of the last call; share one dict across specs hitting the same endpoint."""
    out: list[dict] = []
    pacer = {} if pacer is None else pacer

    def get(params: dict[str, Any]) -> Any:
        if spec.min_interval_s > 0 and spec.path in pacer:
            sleep(max(0.0, spec.min_interval_s - (clock() - pacer[spec.path])))
        try:
            return client.get(spec.path, params)
        finally:
            pacer[spec.path] = clock()

    if spec.max_lookback_days:
        start_ms = max(start_ms, end_ms - spec.max_lookback_days * DAY_MS)
    pending = time_windows(start_ms, end_ms, spec.max_days)
    while pending:
        lo, hi = pending.pop(0)
        base = {**spec.params, spec.time_params[0]: lo, spec.time_params[1]: hi}
        if spec.paging == "none":
            recs = records_of(get({**base, spec.size_param: spec.page_size}))
            if len(recs) >= spec.page_size and hi - lo > 60_000:
                mid = (lo + hi) // 2  # window is full: split it and re-query both halves
                pending[:0] = [(mid + 1, hi), (lo, mid)]
                continue
            out.extend(recs)
            continue
        page = 0 if spec.paging == "offset" else 1
        while True:
            pos = page * spec.page_size if spec.paging == "offset" else page
            recs = records_of(get({**base, spec.paging: pos, spec.size_param: spec.page_size}))
            out.extend(recs)
            if len(recs) < spec.page_size:
                break
            page += 1
    return out


# --- sync ---------------------------------------------------------------------

FIRST_RUN_DAYS = 540


@dataclass
class BinanceSyncResult:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    positions_brl: float = 0.0
    warnings: list[str] = field(default_factory=list)
    ip_restricted: bool | None = None


def upsert_row(conn: sqlite3.Connection, row: dict, now: str) -> str:
    """'inserted' / 'updated' / 'unchanged'.

    A row whose BRL value changed is re-written: an unpriced row once a price exists, and a row priced at a
    close that was later replaced (today's partial close, re-fetched next sync). A row that would lose its
    price (no close available now) keeps the stored value."""
    old = conn.execute("SELECT raw_json, amount_normalized FROM transactions WHERE id = ?",
                       (row["id"],)).fetchone()
    if old and old["raw_json"] == row["raw_json"]:
        now_unpriced = bn.is_unpriced((row["amount"], row["amount_normalized"]))
        if now_unpriced or round(row["amount_normalized"], 6) == round(old["amount_normalized"], 6):
            return "unchanged"
    _upsert(conn, "transactions", {**row, "first_seen_at": now, "updated_at": now}, keep=("first_seen_at",))
    return "updated" if old else "inserted"


def _month_start_ms(ms: int) -> int:
    d = datetime.fromtimestamp(ms / 1000, tz=bn.LOCAL_TZ)
    return int(d.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


def _positions(client: BinanceClient) -> list[tuple[str, str, float]]:
    """(wallet, asset, amount) from spot, simple earn and the funding wallet; LD* mirrors skipped."""
    out: dict[tuple[str, str], float] = {}

    def add(wallet: str, asset: str, amount: float) -> None:
        if amount:
            out[(wallet, asset)] = out.get((wallet, asset), 0.0) + amount

    acct = client.get("/api/v3/account", {"omitZeroBalances": "true"})
    for b in acct.get("balances", []):
        if not b["asset"].startswith("LD"):
            add("spot", b["asset"], float(b["free"]) + float(b["locked"]))
    for r in records_of(client.get("/sapi/v1/simple-earn/flexible/position", {"size": 100})):
        add("earn_flexible", r["asset"], float(r["totalAmount"]))
    for r in records_of(client.get("/sapi/v1/simple-earn/locked/position", {"size": 100})):
        add("earn_locked", r["asset"], float(r["amount"]))
    for w in client.get("/sapi/v1/asset/wallet/balance"):
        if w.get("walletName") == "Funding":
            add("funding", "BTC", float(w["balance"]))
    return [(w, a, amt) for (w, a), amt in out.items()]


def sync_binance(conn: sqlite3.Connection, client: BinanceClient, window_days: int = 30,
                 now_ms: int | None = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> BinanceSyncResult:
    result = BinanceSyncResult()
    result.ip_restricted = client.check_read_only().get("ipRestrict")  # raises before any write

    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    now = datetime.fromtimestamp(now_ms / 1000, tz=UTC).isoformat(timespec="seconds")
    today = bn.local_day(now_ms)
    has_rows = conn.execute("SELECT 1 FROM transactions WHERE account_id = ? LIMIT 1",
                            (bn.ACCOUNT_ID,)).fetchone()
    start_ms = now_ms - (window_days if has_rows else FIRST_RUN_DAYS) * DAY_MS
    if has_rows:  # a gap since the last successful sync longer than the window must still be fetched
        last = conn.execute("SELECT last_updated_at FROM items WHERE id = ?", (bn.ACCOUNT_ID,)).fetchone()
        if last and last[0]:
            last_ms = int(datetime.fromisoformat(last[0]).timestamp() * 1000)
            start_ms = max(now_ms - FIRST_RUN_DAYS * DAY_MS, min(start_ms, last_ms - window_days * DAY_MS))

    pacer: dict[str, float] = {}
    recs = {}
    for name, spec in ENDPOINTS.items():
        # Earn rows are monthly roll-ups: always fetch whole months so a partial sum never overwrites one.
        lo = _month_start_ms(start_ms) if name.startswith(("earn_", "distributions")) else start_ms
        recs[name] = fetch_windowed(client, spec, lo, now_ms, sleep=sleep, clock=clock, pacer=pacer)
    rewards = recs["earn_rewards_realtime"] + recs["earn_rewards_locked"]
    positions = _positions(client)

    # Prices: every coin seen, from the earliest record day to today.
    days: list[str] = []
    assets: set[str] = {a for _w, a, _x in positions}
    for key, coin_key, time_key in (("deposits", "coin", "insertTime"), ("withdrawals", "coin", "applyTime"),
                                    ("earn_rewards_realtime", "asset", "time"),
                                    ("earn_rewards_locked", "asset", "time"),
                                    ("distributions", "asset", "divTime")):
        for r in recs[key]:
            assets.add(r[coin_key])
            days.append(bn.local_day(r[time_key]))
    # Stored rows left at 0 because no price existed: retry them even if outside the fetch window.
    zero = [z for z in conn.execute(
        "SELECT id, currency, date, amount, amount_normalized, raw_json FROM transactions WHERE account_id = ?",
        (bn.ACCOUNT_ID,)) if bn.is_unpriced(dict(z))]
    for z in zero:
        assets.add(z["currency"])
        days.append(z["date"])
        raw = json.loads(z["raw_json"])  # earn lists carry per-item days: price every one of them
        for item in raw if isinstance(raw, list) else []:
            days.append(bn.local_day(item["divTime"] if "divTime" in item else item["time"]))
    warnings = ensure_rates(conn, client, assets, min(days + [today]), today)
    result.warnings.extend(warnings)
    rate_at = rate_fn(conn)

    missing: Counter = Counter()  # asset -> number of items (days) left without a price
    rows = [bn.deposit_row(r, rate_at, missing) for r in recs["deposits"]]
    rows += [bn.withdrawal_row(r, rate_at, missing) for r in recs["withdrawals"]]
    rows += [bn.fiat_row(r, 0) for r in recs["fiat_deposits"]]
    rows += [bn.fiat_row(r, 1) for r in recs["fiat_withdrawals"]]
    rows += bn.earn_rows(rewards, recs["distributions"], rate_at, missing)
    seen = {r["id"] for r in rows if r}
    for z in zero:
        if z["id"] in seen:
            continue
        raw = json.loads(z["raw_json"])
        if z["id"].startswith("binance:dep:"):
            rows.append(bn.deposit_row(raw, rate_at, missing))
        elif z["id"].startswith("binance:wd:"):
            rows.append(bn.withdrawal_row(raw, rate_at, missing))
        elif z["id"].startswith("binance:earn:"):
            rows += bn.earn_rows([x for x in raw if "divTime" not in x],
                                 [x for x in raw if "divTime" in x], rate_at, missing)
    ready: list[dict] = [r for r in rows if r]  # builders return None for failed/pending records

    for asset, n in sorted(missing.items()):  # one warning per asset: how many days had no price
        if n:
            result.warnings.append(f"no price for {asset} on {n} day{'s' if n != 1 else ''}")

    with conn:
        _upsert(conn, "items", bn.item_row(now))
        _upsert(conn, "accounts", bn.account_row(None), keep=("role", "balance"))
        for r in ready:
            outcome = upsert_row(conn, r, now)
            setattr(result, outcome, getattr(result, outcome) + 1)
        total = 0.0
        for wallet, asset, amount in positions:
            rate = rate_at(asset, today)
            value = None if rate is None else round(amount * rate, 2)
            total += value or 0.0
            conn.execute("INSERT OR REPLACE INTO binance_positions(snapshot_at, wallet, asset, amount, brl_value) "
                         "VALUES (?,?,?,?,?)", (now, wallet, asset, amount, value))
        result.positions_brl = round(total, 2)
        conn.execute("UPDATE accounts SET balance = ? WHERE id = ?", (result.positions_brl, bn.ACCOUNT_ID))
    return result
