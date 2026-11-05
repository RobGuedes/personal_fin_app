"""Background sync for the API: one run at a time, in a daemon thread with its own DB connection.

The runner never gets stuck in `running`: every exception (connect, pipeline, report building) ends the run
with an error in `report.errors`. Messages are redacted before they are stored (URLs, opaque ids, documents).
"""

import logging
import re
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

Pipeline = Callable[[sqlite3.Connection, Any, Callable[[str], None]], Any]

_URL = re.compile(r"https?://\S+")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_FORMATTED_DOC = re.compile(r"\d{2,3}\.\d{3}\.\d{3}[/-][\d-]+")
_LONG_DIGITS = re.compile(r"\d{6,}")


def redact(message: str) -> str:
    """Strip what a sync error may embed: request URLs (ids, signatures), UUIDs, documents/account numbers."""
    text = _URL.sub("(url)", str(message))
    text = _UUID.sub("(id)", text)
    text = _FORMATTED_DOC.sub("•••", text)
    text = _LONG_DIGITS.sub("•••", text)
    return text.strip()


def _default_pipeline(conn, settings, progress):
    from finance.pipeline import run_sync

    return run_sync(conn, settings, classify=True, progress=progress)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _report(rep) -> dict:
    """{warnings, errors, counts} from a pipeline SyncReport (duck-typed so tests can fake it)."""
    pluggy, binance = getattr(rep, "pluggy", None), getattr(rep, "binance", None)
    counts = {
        "pluggy": None if pluggy is None else {k: getattr(pluggy, k) for k in
                                               ("items_synced", "inserted", "updated", "deleted")},
        "binance": None if binance is None else {k: getattr(binance, k) for k in ("inserted", "updated", "unchanged")},
        "classified": dict(getattr(rep, "classified", None) or {}) or None,
    }
    return {"warnings": [redact(w) for w in getattr(rep, "warnings", [])],
            "errors": [redact(e) for e in getattr(rep, "errors", [])], "counts": counts}


class SyncRunner:
    def __init__(self, pipeline: Pipeline | None = None) -> None:
        self.pipeline = pipeline or _default_pipeline
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict = {"running": False, "step": None, "started_at": None, "finished_at": None, "report": None}

    def start(self, connect: Callable[[], sqlite3.Connection], settings) -> bool:
        """Start a run; False if one is already running (check-and-set under the lock)."""
        with self._lock:
            if self._state["running"]:
                return False
            self._state = {"running": True, "step": None, "started_at": _now(), "finished_at": None, "report": None}
            self._thread = threading.Thread(target=self._run, args=(connect, settings), name="finance-sync",
                                            daemon=True)
            self._thread.start()
        return True

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def join(self, timeout: float | None = None) -> bool:
        """Wait for the current run (tests, shutdown). True if no run is left alive."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    def _progress(self, step: str) -> None:
        with self._lock:
            self._state["step"] = step

    def _run(self, connect, settings) -> None:
        report = None
        try:
            conn = connect()
            try:
                report = _report(self.pipeline(conn, settings, self._progress))
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001 - the run must always finish with a status
            log.warning("background sync failed: %s", type(e).__name__)
            report = {"warnings": [], "errors": [redact(f"Sincronização: {type(e).__name__}: {e}")],
                      "counts": {"pluggy": None, "binance": None, "classified": None}}
        finally:
            with self._lock:
                self._state.update(running=False, finished_at=_now(),
                                   report=report or {"warnings": [], "errors": ["Sincronização: erro inesperado"],
                                                     "counts": {"pluggy": None, "binance": None, "classified": None}})
