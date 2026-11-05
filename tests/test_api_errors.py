"""Spec §8: every 4xx/5xx body is {"error": "<pt-BR message>", "code": "<slug>"}."""

import pytest

from api_fixtures import MUTATE
from finance import llm


@pytest.fixture(autouse=True)
def no_helper(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "HELPER_BIN", tmp_path / "no-such-helper")


T, R, B = "/api/v1/transactions", "/api/v1/review", "/api/v1/budgets"

CASES = [
    ("get", f"{T}/nope", None, None, 404, "transaction_not_found"),
    ("patch", f"{T}/nope", {"note": "x"}, MUTATE, 404, "transaction_not_found"),
    ("patch", f"{T}/tx-pix-in", {"category_id": "nope"}, MUTATE, 422, "unknown_category"),
    ("patch", f"{T}/tx-pix-in", {"note": "x"}, None, 403, "forbidden"),
    ("post", "/api/v1/health", None, None, 403, "forbidden"),
    ("post", "/api/v1/health", None, MUTATE, 405, "method_not_allowed"),
    ("post", f"{R}/nope/confirm", {"category_id": "groceries"}, MUTATE, 404, "transaction_not_found"),
    ("post", f"{R}/tx-pix-out/confirm", {"category_id": "zzz"}, MUTATE, 422, "unknown_category"),
    ("post", f"{R}/tx-pix-out/confirm", {}, MUTATE, 422, "validation_error"),
    ("post", "/api/v1/rules", {"transaction_id": "nope", "category_id": "services_nf"}, MUTATE, 404,
     "transaction_not_found"),
    ("put", f"{B}/salary", {"monthly_amount": 10}, MUTATE, 422, "not_expense_category"),
    ("put", f"{B}/groceries", {"monthly_amount": 0}, MUTATE, 422, "invalid_amount"),
    ("put", f"{B}/groceries", {"monthly_amount": "abc"}, MUTATE, 422, "validation_error"),
    ("get", "/api/v1/summary/month?month=2026-13", None, None, 422, "validation_error"),
    ("get", "/api/v1/transactions?limit=0", None, None, 422, "validation_error"),
    ("get", "/api/v1/nope", None, None, 404, "not_found"),
]


@pytest.mark.parametrize("method,url,body,headers,status,code", CASES)
def test_error_envelope(api, method, url, body, headers, status, code):
    kwargs = {"headers": headers or {}}
    if body is not None:
        kwargs["json"] = body
    r = getattr(api, method)(url, **kwargs)
    assert r.status_code == status
    data = r.json()
    assert set(data) == {"error", "code"} and data["code"] == code
    assert isinstance(data["error"], str) and data["error"]
    for english in ("not found", "Unknown", "Forbidden", "Field required", "must be", "Not Allowed"):
        assert english not in data["error"]


def test_non_json_body_is_415_envelope(api):
    r = api.post("/api/v1/budgets", content=b"x=1", headers={**MUTATE, "Content-Type": "text/plain"})
    assert r.status_code == 415 and r.json()["code"] == "json_required"


def test_rule_without_matcher_has_code(api):
    ws = api.app.dependency_overrides[next(iter(api.app.dependency_overrides))]()
    ws.conn.execute("UPDATE transactions SET counterparty_name = NULL, counterparty_doc = NULL, description = '' "
                    "WHERE id = 'tx-pix-in'")
    ws.conn.commit()
    r = api.post(f"{R}/tx-pix-in/confirm", json={"category_id": "services_nf", "create_rule": True}, headers=MUTATE)
    assert r.status_code == 422 and r.json()["code"] == "rule_without_matcher"
    assert r.json()["error"].startswith("Não foi possível criar uma regra")


def test_spa_api_404_envelope(tmp_path):
    from fastapi.testclient import TestClient

    from finance.api import create_app
    (tmp_path / "index.html").write_text("<html>app</html>")
    with TestClient(create_app(static_dir=tmp_path), base_url="http://localhost") as c:
        r = c.get("/api/v1/nope")
        assert r.status_code == 404 and r.json()["code"] == "not_found"
