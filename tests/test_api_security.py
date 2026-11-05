from api_fixtures import MUTATE


def test_health_ok(api):
    r = api.get("/api/v1/health")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_rejects_foreign_host(api):
    assert api.get("/api/v1/health", headers={"Host": "evil.example"}).status_code == 400


def test_mutation_needs_custom_header(api):
    assert api.post("/api/v1/health").status_code == 403
    assert api.post("/api/v1/health", headers=MUTATE).status_code == 405


def test_mutation_rejects_foreign_origin(api):
    r = api.post("/api/v1/health", headers={**MUTATE, "Origin": "https://evil.example"})
    assert r.status_code == 403
    assert api.post("/api/v1/health", headers={**MUTATE, "Origin": "http://localhost:5173"}).status_code == 405


def test_mutation_rejects_non_json_body(api):
    r = api.post("/api/v1/health", content=b"x=1", headers={**MUTATE, "Content-Type": "text/plain"})
    assert r.status_code == 415


def test_no_cors_headers(api):
    r = api.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_static_spa_fallback(tmp_path):
    from fastapi.testclient import TestClient

    from finance.api import create_app
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "a.js").write_text("x")
    with TestClient(create_app(static_dir=tmp_path), base_url="http://localhost") as c:
        assert c.get("/some/route").text == "<html>app</html>"
        assert c.get("/a.js").text == "x"
        assert c.get("/../../etc/passwd").text == "<html>app</html>"
        assert c.get("/api/v1/nope").status_code == 404
        assert c.get("/api/v1/health").json() == {"ok": True}


def test_default_workspace_closes_connection_per_request(tmp_path, monkeypatch):
    import sqlite3

    import pytest
    from fastapi import Depends
    from fastapi.testclient import TestClient

    from finance.api import Workspace, create_app, deps, get_workspace
    from finance.db import connect

    opened = []

    def spy_connect():
        opened.append(connect(tmp_path / "spy.db"))
        return opened[-1]

    monkeypatch.setattr(deps, "connect", spy_connect)
    monkeypatch.setattr(deps, "load_settings", lambda: object())  # never read .env
    deps._taxonomy.cache_clear()
    deps._settings.cache_clear()
    app = create_app()
    @app.get("/api/v1/_probe")
    def probe(ws: Workspace = Depends(get_workspace)):
        return {"n": ws.conn.execute("SELECT 1").fetchone()[0]}

    with TestClient(app, base_url="http://localhost") as c:
        assert c.get("/api/v1/_probe").json() == {"n": 1}
        assert c.get("/api/v1/_probe").json() == {"n": 1}
    assert len(opened) == 2
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")
    deps._taxonomy.cache_clear()
    deps._settings.cache_clear()


def test_security_headers_on_api_and_static(tmp_path):
    """Anti-framing (clickjacking), nosniff, CSP and CORP on every response, API and SPA alike."""
    from fastapi.testclient import TestClient

    from finance.api import create_app
    (tmp_path / "index.html").write_text("<html>app</html>")
    with TestClient(create_app(static_dir=tmp_path), base_url="http://localhost") as c:
        for r in (c.get("/"), c.get("/api/v1/health"), c.get("/api/v1/nope"), c.post("/api/v1/health")):
            assert r.headers["x-frame-options"] == "DENY"
            assert r.headers["x-content-type-options"] == "nosniff"
            assert r.headers["referrer-policy"] == "no-referrer"
            assert r.headers["cross-origin-resource-policy"] == "same-origin"
            csp = r.headers["content-security-policy"]
            assert "frame-ancestors 'none'" in csp and "script-src 'self'" in csp and "default-src 'self'" in csp


def test_cross_site_reads_are_refused(api):
    """<img src="http://127.0.0.1:8600/api/v1/review"> on another site must not run anything."""
    assert api.get("/api/v1/health", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert api.get("/api/v1/health", headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
    assert api.get("/api/v1/health", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert api.get("/api/v1/health", headers={"Sec-Fetch-Site": "none"}).status_code == 200  # typed URL
    assert api.get("/api/v1/health").status_code == 200  # curl / non-browser clients
