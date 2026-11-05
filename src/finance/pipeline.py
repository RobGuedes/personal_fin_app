"""One sync pipeline shared by the CLI (`finance sync`) and the API (background sync)."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from finance import aggregate, networth
from finance.binance_client import BinanceClient, BinanceError
from finance.binance_sync import BinanceSyncResult, sync_binance
from finance.classify import classify_all, load_rules_config, load_taxonomy
from finance.normalize import LOCAL_TZ
from finance.sync import SyncResult, _now, sync


@dataclass
class SyncReport:
    pluggy: SyncResult | None = None
    binance: BinanceSyncResult | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    classified: dict[str, int] | None = None
    started_at: str = ""
    finished_at: str = ""


def _http_error(prefix: str, e: httpx.HTTPError) -> str:
    # str(e) may embed the request URL with its signature query: report only class and path.
    try:
        path = f" ({e.request.url.path})"
    except Exception:
        path = ""
    return f"{prefix}: {type(e).__name__}{path}"


def run_binance(conn, settings, window_days: int, client_factory=None):
    """Sync Binance; returns (result, errors). Never raises; (None, []) when no key is configured."""
    if not settings.binance_api_key:
        return None, []
    factory = client_factory or BinanceClient
    try:
        with factory(settings) as client:
            return sync_binance(conn, client, window_days=window_days), []
    except BinanceError as e:
        return None, [f"Binance: {e}"]
    except httpx.HTTPError as e:
        return None, [_http_error("Binance", e)]
    except sqlite3.Error as e:
        return None, [f"Binance: {type(e).__name__}: {e}"]
    except Exception as e:  # bad JSON (maintenance page), a record missing a key, ...: report, never crash
        conn.rollback()
        return None, [f"Binance: {type(e).__name__}"]


def _run_investments(conn, client, item_ids) -> tuple[bool, list[str]]:
    """Per item, so one failing item leaves its stored positions alone. ok only if every item worked."""
    errors = []
    for n, item_id in enumerate(item_ids, 1):
        try:
            networth.sync_investments(conn, client, [item_id])
        except Exception as e:
            conn.rollback()
            errors.append(f"Investimentos: item {n}: {type(e).__name__}")
    return not errors, errors


def _run_pluggy(conn, settings, window_days, factory, wealth: dict | None = None):
    if factory is None:
        from finance.pluggy_client import PluggyClient as factory
    wealth = wealth if wealth is not None else {}
    try:
        with factory(settings) as client:
            result = sync(conn, client, settings.pluggy_item_ids, window_days=window_days)
            # same Pluggy session (API key) for the investments
            wealth["investments_ok"], errs = _run_investments(conn, client, settings.pluggy_item_ids)
            return result, errs
    except httpx.HTTPError as e:
        return None, [_http_error("Pluggy", e)]
    except Exception as e:  # the API calls this from a thread: never crash, report instead
        return None, [f"Pluggy: {type(e).__name__}: {e}"]


def _sync_wealth(conn, report: SyncReport, wealth: dict, binance_errors: list[str]) -> None:
    """Snapshot only the groups whose source succeeded today; a failed source is never written as 0."""
    try:
        groups: set[str] = set()
        if report.pluggy is not None and not report.pluggy.errors:
            groups |= {"accounts", "cards"}  # a partial bank total would look like a drop
        if wealth.get("investments_ok"):
            groups.add("investments")
        if report.binance is not None and not binance_errors and aggregate.binance_holdings(conn) is not None:
            groups.add("crypto")
        if groups:
            day = datetime.now(LOCAL_TZ).date().isoformat()
            networth.snapshot(conn, day, groups, networth.group_totals(conn))
    except Exception as e:
        report.errors.append(f"Patrimônio: {type(e).__name__}: {e}")


def run_sync(conn, settings, window_days: int = 30, skip_binance: bool = False, classify: bool = True,
             progress: Callable[[str], None] = lambda s: None, *,
             pluggy_client_factory=None, binance_client_factory=None) -> SyncReport:
    report = SyncReport(started_at=_now())

    progress("Bancos (Pluggy)")
    wealth: dict = {}
    report.pluggy, errs = _run_pluggy(conn, settings, window_days, pluggy_client_factory, wealth)
    report.errors += (report.pluggy.errors if report.pluggy else []) + errs

    binance_errors: list[str] = []
    if not skip_binance:
        progress("Binance")
        report.binance, errs = run_binance(conn, settings, window_days, binance_client_factory)
        if report.binance is not None:
            report.warnings += report.binance.warnings
            if report.binance.ip_restricted is False:
                report.warnings.append("A chave da Binance não tem restrição de IP.")
        report.errors += errs
        binance_errors = errs

    progress("Patrimônio")
    _sync_wealth(conn, report, wealth, binance_errors)

    if classify:
        progress("Classificação")
        try:
            report.classified = classify_all(conn, load_taxonomy(), load_rules_config(),
                                             settings.my_cpf, settings.my_name)
        except Exception as e:
            report.errors.append(f"Classificação: {type(e).__name__}: {e}")

    report.finished_at = _now()
    return report
