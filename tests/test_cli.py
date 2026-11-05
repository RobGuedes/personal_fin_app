import pytest
from pydantic import SecretStr

from finance import cli, pipeline
from finance.binance_client import BinanceError
from finance.cli import build_parser, run_binance
from finance.config import Settings
from finance.db import connect


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    yield c
    c.close()


def _settings(key="k", secret="s"):
    return Settings(pluggy_client_id="a", pluggy_client_secret="b",
                    binance_api_key=key, binance_api_secret=SecretStr(secret))


def test_run_binance_skipped_without_key(conn):
    assert run_binance(conn, _settings(key="", secret=""), 30) == (None, [])


def test_binance_failure_keeps_pluggy(conn, monkeypatch):
    conn.execute("INSERT INTO items (id, raw_json) VALUES ('item-1', '{}')")
    conn.execute("INSERT INTO accounts (id, item_id, type, subtype, name, raw_json) "
                 "VALUES ('acc-1', 'item-1', 'BANK', 'CHECKING_ACCOUNT', 'x', '{}')")
    conn.commit()

    class FakeClient:
        def __init__(self, settings): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def boom(*a, **k):
        raise BinanceError("HTTP 418 teapot")

    monkeypatch.setattr(pipeline, "BinanceClient", FakeClient)
    monkeypatch.setattr(pipeline, "sync_binance", boom)
    result, errors = run_binance(conn, _settings(), 30)
    assert result is None
    assert len(errors) == 1 and errors[0].startswith("Binance: ") and "418" in errors[0]
    assert conn.execute("SELECT COUNT(*) FROM accounts WHERE id = 'acc-1'").fetchone()[0] == 1


def test_sync_parser_has_skip_binance():
    assert build_parser().parse_args(["sync", "--skip-binance"]).skip_binance
    assert not build_parser().parse_args(["sync"]).skip_binance


def test_httpx_error_is_reported_without_signature(conn, monkeypatch):
    import httpx

    class FakeClient:
        def __init__(self, settings): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def boom(*a, **k):
        req = httpx.Request("GET", "https://api.binance.com/api/v3/account?timestamp=1&signature=deadbeef")
        raise httpx.ConnectError("connect failed for https://x?signature=deadbeef", request=req)

    monkeypatch.setattr(pipeline, "BinanceClient", FakeClient)
    monkeypatch.setattr(pipeline, "sync_binance", boom)
    result, errors = run_binance(conn, _settings(), 30)
    assert result is None and len(errors) == 1
    assert errors[0].startswith("Binance: ConnectError")
    assert "signature" not in errors[0] and "deadbeef" not in errors[0]


def _patch_pluggy(monkeypatch, tmp_path):
    from finance import config, db, pluggy_client
    from finance import sync as sync_mod

    class FakeClient:
        def __init__(self, settings): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(config, "load_settings", lambda: _settings())
    monkeypatch.setattr(db, "connect", lambda *a, **k: connect(tmp_path / "c.db"))
    monkeypatch.setattr(pluggy_client, "PluggyClient", FakeClient)
    monkeypatch.setattr(pipeline, "sync", lambda *a, **k: sync_mod.SyncResult())


def test_cmd_sync_prints_binance_summary(monkeypatch, tmp_path, capsys):
    from finance.binance_sync import BinanceSyncResult

    _patch_pluggy(monkeypatch, tmp_path)
    res = BinanceSyncResult(inserted=2, updated=1, unchanged=3, positions_brl=1234.5,
                            warnings=["something odd"], ip_restricted=False)
    monkeypatch.setattr(pipeline, "run_binance", lambda *a, **k: (res, []))
    code = cli.main(["sync"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Binance: inserted=2 updated=1 unchanged=3 holdings=R$ 1.234,50" in out
    assert "something odd" in out
    assert "WARNING: Binance key is not IP-restricted" in out


def test_cmd_sync_skip_binance(monkeypatch, tmp_path):
    _patch_pluggy(monkeypatch, tmp_path)

    def fail(*a, **k):
        raise AssertionError("run_binance must not be called")

    monkeypatch.setattr(pipeline, "run_binance", fail)
    assert cli.main(["sync", "--skip-binance"]) == 0


def test_cmd_sync_binance_error_exit_1(monkeypatch, tmp_path, capsys):
    _patch_pluggy(monkeypatch, tmp_path)
    monkeypatch.setattr(pipeline, "run_binance", lambda *a, **k: (None, ["Binance: boom"]))
    assert cli.main(["sync"]) == 1
    assert "ERROR Binance: boom" in capsys.readouterr().out


def test_cmd_app_migrates_once_before_serving(monkeypatch, tmp_path):
    """The first start after a merge must migrate before uvicorn accepts parallel requests."""
    import sqlite3

    import uvicorn

    import finance.api
    from finance.db import MIGRATIONS

    db_path = tmp_path / "v4.db"
    raw = sqlite3.connect(db_path)
    with raw:
        for sql in MIGRATIONS[:4]:
            raw.executescript(sql)
        raw.execute("PRAGMA user_version = 4")
    raw.close()
    monkeypatch.setenv("FINANCE_DB", str(db_path))
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>")
    monkeypatch.setattr(cli, "WEB_DIST", dist)
    monkeypatch.setattr(finance.api, "create_app", lambda **kw: object())
    seen = {}

    def fake_run(app, **kw):
        check = sqlite3.connect(db_path)
        seen["version"] = check.execute("PRAGMA user_version").fetchone()[0]
        check.close()

    monkeypatch.setattr(uvicorn, "run", fake_run)
    assert cli.cmd_app(build_parser().parse_args(["app", "--no-open", "--port", "8699"])) == 0
    assert seen["version"] == len(MIGRATIONS)


def test_cli_closes_the_connection_it_opened(monkeypatch, tmp_path):
    import sqlite3

    import pytest

    from finance import cli, db

    opened = []
    real_connect = db.connect

    def spy(*a, **k):
        opened.append(real_connect(tmp_path / "t.db"))
        return opened[-1]

    monkeypatch.setattr(db, "connect", spy)
    cli.main(["classify", "--months", "1"])
    assert opened
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")
