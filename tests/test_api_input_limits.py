"""Input bounds: non-finite or absurd numbers and oversized/invalid text must be 422, never stored or 500."""

import json

import pytest

from api_fixtures import MUTATE


def _post(api, path, body, method="post"):
    # Raw JSON so NaN/Infinity reach the server the way a hand-made request would send them.
    return api.request(method.upper(), f"/api/v1{path}", content=json.dumps(body, allow_nan=True),
                       headers={**MUTATE, "Content-Type": "application/json"})


@pytest.mark.parametrize("value", [float("inf"), float("nan"), 1e308, -5, 0])
def test_budget_amount_must_be_finite_positive_and_bounded(api, value):
    r = _post(api, "/budgets/groceries", {"monthly_amount": value}, "put")
    assert r.status_code == 422 and "error" in r.json()
    assert api.get("/api/v1/budgets").json() == {}


@pytest.mark.parametrize("value", [float("inf"), float("nan"), 1e308, -1e12])
def test_manual_entry_amount_is_bounded(api, value):
    before = api.get("/api/v1/manual-entries").json()
    r = _post(api, "/manual-entries", {"month": "2026-10", "pnl_line": "income", "amount": value, "note": "x"})
    assert r.status_code == 422
    assert api.get("/api/v1/manual-entries").json() == before
    assert api.get("/api/v1/sankey?period=last12").status_code == 200


def test_manual_entry_month_must_be_a_real_month(api):
    r = _post(api, "/manual-entries", {"month": "2026-13", "pnl_line": "income", "amount": 10, "note": "x"})
    assert r.status_code == 422


@pytest.mark.parametrize("note", ["x" * 501, "a\x00b", "bad \ud800 surrogate"])
def test_transaction_note_is_bounded_and_clean(api, note):
    r = _post(api, "/transactions/tx-pix-out", {"note": note}, "patch")
    assert r.status_code == 422 and r.json()["code"]
    r = _post(api, "/review/tx-pix-out/confirm", {"category_id": "groceries", "note": note})
    assert r.status_code == 422


def test_transaction_note_keeps_normal_text(api):
    r = _post(api, "/transactions/tx-pix-out", {"note": "Pizza com a família 🍕\nlinha 2"}, "patch")
    assert r.status_code == 200


@pytest.mark.parametrize("previous", [
    {"category_id": "groceries", "source": "manual", "confidence": float("nan")},
    {"category_id": "groceries", "source": "manual", "confidence": 1e999},
    {"category_id": "groceries", "source": "manual", "confidence": 1.5},
    {"category_id": "groceries", "source": "hacker", "confidence": 1},
])
def test_undo_validates_the_previous_classification(api, previous):
    r = _post(api, "/review/tx-pix-out/undo", {"previous": previous})
    assert r.status_code == 422


def test_undo_accepts_a_real_previous_classification(api):
    r = _post(api, "/review/tx-pix-out/undo",
              {"previous": {"category_id": "groceries", "source": "rule", "rule_id": "r1", "confidence": 0.9}})
    assert r.status_code == 200
