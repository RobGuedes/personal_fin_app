import pytest
from pydantic import SecretStr

from finance import cli, pipeline
from finance.config import Settings
from finance.db import connect


def _settings(key="k"):
    return Settings(pluggy_client_id="a", pluggy_client_secret="b", pluggy_item_ids=["i1", "i2"],
                    binance_api_key=key, binance_api_secret=SecretStr("s" if key else ""))


def _fake_result():
    from finance.sync import SyncResult

    return SyncResult(items_synced=1, inserted=3, updated=2, deleted=1, errors=["item i2: boom"],
                      accounts=[{"name": "Conta", "subtype": "CHECKING_ACCOUNT", "number": "1234-5",
                                 "mode": "full", "fetched": 5, "inserted": 3, "updated": 2,
                                 "unchanged": 0, "deleted": 1}])


def test_cli_sync_output_unchanged(monkeypatch, tmp_path, capsys):
    from finance import config, db, pluggy_client
    from finance.binance_sync import BinanceSyncResult

    class FakeClient:
        def __init__(self, settings): pass
        def list_investments(self, item_id): return []
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(config, "load_settings", lambda: _settings())
    monkeypatch.setattr(db, "connect", lambda *a, **k: connect(tmp_path / "c.db"))
    monkeypatch.setattr(pluggy_client, "PluggyClient", FakeClient)
    monkeypatch.setattr(pipeline, "sync", lambda *a, **k: _fake_result())
    res = BinanceSyncResult(inserted=2, updated=1, unchanged=3, positions_brl=1234.5,
                            warnings=["something odd"], ip_restricted=False)
    monkeypatch.setattr(pipeline, "run_binance", lambda *a, **k: (res, []))
    code = cli.main(["sync"])
    out = capsys.readouterr().out
    assert code == 1
    assert out.split("\nBalance check:")[0] == (
        "Items synced: 1/2  inserted=3 updated=2 deleted=1\n"
        "  Conta [CHECKING_ACCOUNT] 1234-5: full, fetched=5 inserted=3 updated=2 unchanged=0 deleted=1\n"
        "  ERROR item i2: boom\n"
        "Binance: inserted=2 updated=1 unchanged=3 holdings=R$ 1.234,50\n"
        "  WARNING something odd\n"
        "  WARNING: Binance key is not IP-restricted\n"
    )


class _Ctx:
    def __init__(self, *a, **k): pass
    def list_investments(self, item_id): return []
    def __enter__(self): return self
    def __exit__(self, *a): return False


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "p.db")
    yield c
    c.close()


def test_pipeline_runs_pluggy_then_binance_then_classify(conn, monkeypatch):
    from finance import pipeline
    from finance.binance_sync import BinanceSyncResult

    calls = []
    monkeypatch.setattr(pipeline, "sync", lambda *a, **k: calls.append("pluggy") or _fake_result())
    monkeypatch.setattr(pipeline, "sync_binance",
                        lambda *a, **k: calls.append("binance") or BinanceSyncResult(inserted=1))
    monkeypatch.setattr(pipeline, "classify_all", lambda *a, **k: calls.append("classify") or {"rule": 4})
    steps = []
    report = pipeline.run_sync(conn, _settings(), progress=steps.append,
                               pluggy_client_factory=_Ctx, binance_client_factory=_Ctx)
    assert steps == ["Bancos (Pluggy)", "Binance", "Patrimônio", "Classificação"]
    assert calls == ["pluggy", "binance", "classify"]
    assert report.pluggy.inserted == 3 and report.binance.inserted == 1
    assert report.classified == {"rule": 4}
    assert report.errors == ["item i2: boom"]
    assert report.started_at <= report.finished_at


def test_binance_failure_keeps_pluggy_and_reports_error(conn, monkeypatch):
    from finance import pipeline
    from finance.binance_client import BinanceError

    def boom(*a, **k):
        raise BinanceError("HTTP 418 teapot")

    monkeypatch.setattr(pipeline, "sync", lambda *a, **k: _fake_result())
    monkeypatch.setattr(pipeline, "sync_binance", boom)
    report = pipeline.run_sync(conn, _settings(), classify=False,
                               pluggy_client_factory=_Ctx, binance_client_factory=_Ctx)
    assert report.pluggy.inserted == 3 and report.binance is None and report.classified is None
    assert any(e.startswith("Binance: ") and "418" in e for e in report.errors)


def test_pluggy_exception_is_reported_and_binance_still_runs(conn, monkeypatch):
    from finance import pipeline
    from finance.binance_sync import BinanceSyncResult

    def boom(*a, **k):
        raise RuntimeError("auth failed")

    monkeypatch.setattr(pipeline, "sync", boom)
    monkeypatch.setattr(pipeline, "sync_binance", lambda *a, **k: BinanceSyncResult())
    report = pipeline.run_sync(conn, _settings(), classify=False,
                               pluggy_client_factory=_Ctx, binance_client_factory=_Ctx)
    assert report.pluggy is None and report.binance is not None
    assert report.errors == ["Pluggy: RuntimeError: auth failed"]


def _wealth_setup(conn, monkeypatch, pluggy_errors=None, binance_ok=True, holdings=True):
    from finance import pipeline
    from finance.binance_sync import BinanceSyncResult
    from finance.sync import SyncResult

    for i in ("i1", "i2"):
        conn.execute("INSERT INTO items (id, raw_json) VALUES (?, '{}')", (i,))
    conn.execute("INSERT INTO accounts (id, item_id, type, balance, raw_json) VALUES ('a','i1','BANK',100,'{}')")
    conn.execute("INSERT INTO accounts (id, item_id, type, balance, raw_json) VALUES ('c','i1','CREDIT',30,'{}')")
    if holdings:
        conn.execute("INSERT INTO binance_positions VALUES ('2026-11-01T10:00:00','spot','BTC',1,500)")
    conn.commit()
    monkeypatch.setattr(pipeline, "sync", lambda *a, **k: SyncResult(errors=pluggy_errors or []))
    if binance_ok:
        monkeypatch.setattr(pipeline, "sync_binance", lambda *a, **k: BinanceSyncResult())
    else:
        from finance.binance_client import BinanceError

        def boom(*a, **k):
            raise BinanceError("down")
        monkeypatch.setattr(pipeline, "sync_binance", boom)


def _snap(conn):
    return {r[0]: r[1] for r in conn.execute("SELECT grp, value FROM net_worth_snapshots")}


def test_wealth_snapshot_all_groups(conn, monkeypatch):
    _wealth_setup(conn, monkeypatch)
    pipeline_run(conn)
    assert _snap(conn) == {"accounts": 100, "cards": -30, "investments": 0, "crypto": 500}


def test_wealth_pluggy_item_error_skips_accounts_and_cards(conn, monkeypatch):
    _wealth_setup(conn, monkeypatch, pluggy_errors=["item 2: boom"])
    pipeline_run(conn)
    assert set(_snap(conn)) == {"investments", "crypto"}


def test_wealth_binance_failure_or_skip_writes_no_crypto(conn, monkeypatch):
    _wealth_setup(conn, monkeypatch, binance_ok=False)
    pipeline_run(conn)
    assert "crypto" not in _snap(conn) and "accounts" in _snap(conn)
    conn.execute("DELETE FROM net_worth_snapshots")
    pipeline_run(conn, skip_binance=True)
    assert "crypto" not in _snap(conn)


def test_wealth_no_holdings_writes_no_crypto(conn, monkeypatch):
    _wealth_setup(conn, monkeypatch, holdings=False)
    pipeline_run(conn)
    assert "crypto" not in _snap(conn)


def test_wealth_investment_failure_keeps_positions_and_skips_group(conn, monkeypatch):
    _wealth_setup(conn, monkeypatch)
    conn.execute("INSERT INTO investments (id, item_id, balance, currency, raw_json, updated_at) "
                 "VALUES ('p','i2',9,'BRL','{}','x')")
    conn.commit()

    class Ctx(_Ctx):
        def list_investments(self, item_id):
            if item_id == "i2":
                raise RuntimeError("secret detail")
            return []

    report = pipeline_run(conn, factory=Ctx)
    assert "investments" not in _snap(conn) and "accounts" in _snap(conn)
    assert conn.execute("SELECT COUNT(*) FROM investments").fetchone()[0] == 1
    assert report.errors == ["Investimentos: item 2: RuntimeError"]


def pipeline_run(conn, skip_binance=False, factory=_Ctx):
    from finance import pipeline

    return pipeline.run_sync(conn, _settings(), classify=False, skip_binance=skip_binance,
                             pluggy_client_factory=factory, binance_client_factory=_Ctx)


def test_unrestricted_binance_key_warning_is_pt_br(conn, monkeypatch):
    from finance import pipeline
    from finance.binance_sync import BinanceSyncResult

    monkeypatch.setattr(pipeline, "sync", lambda *a, **k: _fake_result())
    monkeypatch.setattr(pipeline, "sync_binance", lambda *a, **k: BinanceSyncResult(ip_restricted=False))
    report = pipeline.run_sync(conn, _settings(), classify=False,
                               pluggy_client_factory=_Ctx, binance_client_factory=_Ctx)
    assert "A chave da Binance não tem restrição de IP." in report.warnings


@pytest.mark.parametrize("exc", [ValueError("Expecting value: line 1 column 1"), KeyError("network")])
def test_unexpected_binance_error_is_reported_and_later_steps_run(conn, monkeypatch, exc):
    """A maintenance HTML page (JSON error) or a record missing a key must not crash the sync."""
    from finance import pipeline

    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(pipeline, "sync", lambda *a, **k: _fake_result())
    monkeypatch.setattr(pipeline, "sync_binance", boom)
    monkeypatch.setattr(pipeline, "classify_all", lambda *a, **k: {"rule": 1})
    steps = []
    report = pipeline.run_sync(conn, _settings(), progress=steps.append,
                               pluggy_client_factory=_Ctx, binance_client_factory=_Ctx)
    assert steps[-1] == "Classificação" and report.classified == {"rule": 1}
    assert f"Binance: {type(exc).__name__}" in report.errors


def test_holdings_failure_during_snapshot_is_reported(conn, monkeypatch):
    from finance import pipeline
    from finance.binance_sync import BinanceSyncResult

    def boom(conn):
        raise ValueError("bad row")

    monkeypatch.setattr(pipeline, "sync", lambda *a, **k: _fake_result())
    monkeypatch.setattr(pipeline, "sync_binance", lambda *a, **k: BinanceSyncResult())
    monkeypatch.setattr(pipeline.aggregate, "binance_holdings", boom)
    monkeypatch.setattr(pipeline, "classify_all", lambda *a, **k: {})
    report = pipeline.run_sync(conn, _settings(), pluggy_client_factory=_Ctx, binance_client_factory=_Ctx)
    assert any(e.startswith("Patrimônio: ValueError") for e in report.errors)
    assert report.classified == {}
