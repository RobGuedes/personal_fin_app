"""Daily BRL prices from Binance klines, cached in the fx_rates table."""
import sqlite3
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from functools import partial

from finance.binance_client import BinanceClient, UnknownSymbolError

LOCAL_TZ = timezone(timedelta(hours=-3))
DAY_MS = 86_400_000
FALLBACK_DAYS = 3


def _day_ms(day: str) -> int:
    d = date.fromisoformat(day)
    return int(datetime(d.year, d.month, d.day, tzinfo=LOCAL_TZ).timestamp() * 1000)


def _days(start_day: str, end_day: str) -> list[str]:
    s, e = date.fromisoformat(start_day), date.fromisoformat(end_day)
    return [(s + timedelta(days=i)).isoformat() for i in range((e - s).days + 1)]


def _fetch(conn: sqlite3.Connection, client: BinanceClient, pair: str,
           start_day: str, end_day: str, unknown: set[str], fresh: set[str]) -> bool:
    """Fill missing days of `pair`; return False if the symbol does not exist."""
    if pair in unknown:
        return False
    # The last stored day may be a partial (intraday) close: re-fetch from it onward and replace.
    last = conn.execute("SELECT MAX(date) FROM fx_rates WHERE pair = ?", (pair,)).fetchone()[0]
    if last is not None and last <= end_day and pair not in fresh:
        start_day = min(start_day, last)
    have = {r[0] for r in conn.execute(
        "SELECT date FROM fx_rates WHERE pair = ? AND date BETWEEN ? AND ?",
        (pair, start_day, end_day))}
    missing = [d for d in _days(start_day, end_day) if d not in have or (d == last and pair not in fresh)]
    if not missing:
        return True
    try:
        rows = client.klines(pair, _day_ms(missing[0]), _day_ms(missing[-1]) + DAY_MS - 1)
    except UnknownSymbolError:
        unknown.add(pair)
        return False
    fresh.add(pair)
    with conn:
        for day, close in rows:
            conn.execute("INSERT OR REPLACE INTO fx_rates(date, pair, close) VALUES (?,?,?)",
                         (day, pair, close))
    return True


def ensure_rates(conn: sqlite3.Connection, client: BinanceClient, assets: set[str],
                 start_day: str, end_day: str) -> list[str]:
    warnings: list[str] = []
    unknown: set[str] = set()
    fresh: set[str] = set()  # pairs already refreshed in this call
    for asset in sorted(assets - {"BRL"}):
        if _fetch(conn, client, f"{asset}BRL", start_day, end_day, unknown, fresh):
            continue
        if asset != "USDT" and _fetch(conn, client, f"{asset}USDT", start_day, end_day, unknown, fresh):
            _fetch(conn, client, "USDTBRL", start_day, end_day, unknown, fresh)
        else:
            warnings.append(f"no price for {asset}")
    return warnings


def _close(conn: sqlite3.Connection, pair: str, day: str) -> float | None:
    lo = (date.fromisoformat(day) - timedelta(days=FALLBACK_DAYS)).isoformat()
    row = conn.execute(
        "SELECT close FROM fx_rates WHERE pair = ? AND date <= ? AND date >= ? "
        "ORDER BY date DESC LIMIT 1", (pair, day, lo)).fetchone()
    return row[0] if row else None


def rate(conn: sqlite3.Connection, asset: str, day: str) -> float | None:
    if asset == "BRL":
        return 1.0
    direct = _close(conn, f"{asset}BRL", day)
    if direct is not None:
        return direct
    usdt, brl = _close(conn, f"{asset}USDT", day), _close(conn, "USDTBRL", day)
    return usdt * brl if usdt is not None and brl is not None else None


def rate_fn(conn: sqlite3.Connection) -> Callable[[str, str], float | None]:
    return partial(rate, conn)
