"""Request-scoped dependencies. Nothing here touches the real DB at import time."""

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from finance.classify import Taxonomy, load_taxonomy
from finance.config import CONFIG_DIR, Settings, load_settings
from finance.db import connect


@dataclass
class Workspace:
    conn: sqlite3.Connection
    taxonomy: Taxonomy
    rules_path: Path
    settings: Settings


@lru_cache(maxsize=1)
def _taxonomy() -> Taxonomy:
    return load_taxonomy()


@lru_cache(maxsize=1)
def _settings() -> Settings:
    return load_settings()


def get_workspace() -> Iterator[Workspace]:
    """Default dependency: one connection per request, always closed. Taxonomy/settings are loaded once.

    Overridden in tests / via create_app(workspace_factory=...)."""
    conn = connect()
    try:
        yield Workspace(conn=conn, taxonomy=_taxonomy(), rules_path=CONFIG_DIR / "rules.yaml", settings=_settings())
    finally:
        conn.close()
