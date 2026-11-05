import re

import pytest

from api_fixtures import MUTATE
from finance import aggregate as agg
from finance import llm
from finance.api.routes.transactions import _rows

URL = "/api/v1/review"


def _ws(client):
    return client.app.dependency_overrides[next(iter(client.app.dependency_overrides))]()


@pytest.fixture(autouse=True)
def no_helper(monkeypatch, tmp_path):
    """Tests never start the on-device model helper."""
    monkeypatch.setattr(llm, "HELPER_BIN", tmp_path / "no-such-helper")


def _classification(ws, tx_id):
    r = ws.conn.execute("SELECT * FROM classifications WHERE transaction_id = ?", (tx_id,)).fetchone()
    return dict(r) if r else None


def test_inbox_equals_review_queue_ids(api):
    ws = _ws(api)
    ws.conn.execute("UPDATE classifications SET confidence = 0.4 WHERE transaction_id = 'tx-pix-out'")
    ws.conn.commit()
    expected = {r["id"] for r in agg.review_queue(_rows(ws), ws.taxonomy.settings["review_confidence_below"])}
    items = api.get(URL).json()
    ids = [i["id"] for i in items]
    assert set(ids) == expected and "tx-pix-in" in ids and "tx-pix-out" in ids
    assert len(ids) == len(set(ids))
    dates = [i["date"] for i in items]
    assert dates == sorted(dates, reverse=True)
    assert all("counterparty_doc" not in i for i in items)


def test_low_confidence_item_listed_once(api):
    ws = _ws(api)
    ws.conn.execute("UPDATE classifications SET confidence = 0.3 WHERE transaction_id = 'tx-card-buy'")
    ws.conn.commit()
    ids = [i["id"] for i in api.get(URL).json()]
    assert ids.count("tx-card-buy") == 1


def test_past_choice_suggestion_reason(api):
    ws = _ws(api)
    ws.conn.execute("UPDATE transactions SET counterparty_name = 'EMPRESA CLIENTE LTDA' WHERE id = 'tx-pix-out'")
    ws.conn.commit()
    from finance.classify import set_manual
    set_manual(ws.conn, "tx-pix-out", "groceries", ws.taxonomy)
    item = next(i for i in api.get(URL).json() if i["id"] == "tx-pix-in")
    assert item["suggestion"]["category_id"] == "groceries"
    assert item["suggestion"]["reason"] == "past_choice"
    assert re.search(r"\d\d/\d\d", item["suggestion"]["detail"])
    assert item["top_categories"] == []  # the only manual choice is an outflow; this item is an inflow


def test_model_suggestion_and_none(api):
    ws = _ws(api)
    item = next(i for i in api.get(URL).json() if i["id"] == "tx-pix-in")
    assert item["suggestion"] is None
    ws.conn.execute("INSERT INTO llm_suggestions (transaction_id, category_id, prompt_version, created_at) "
                    "VALUES ('tx-pix-in', 'services_nf', ?, 'x')", (llm.PROMPT_VERSION,))
    ws.conn.commit()
    item = next(i for i in api.get(URL).json() if i["id"] == "tx-pix-in")
    assert item["suggestion"]["reason"] == "model" and item["suggestion"]["category_id"] == "services_nf"
    assert item["suggestion"]["detail"] == "Sugestão do modelo no Mac"


def test_confirm_then_undo_restores_previous(api):
    ws = _ws(api)
    r = api.post(f"{URL}/tx-pix-out/confirm", json={"category_id": "groceries"}, headers=MUTATE)
    assert r.status_code == 200
    body = r.json()
    assert body["previous"] == {"category_id": "shopping", "source": "pluggy_map", "rule_id": None, "confidence": 0.7}
    assert body["rule_id"] is None
    assert _classification(ws, "tx-pix-out")["source"] == "manual"
    u = api.post(f"{URL}/tx-pix-out/undo", json={"previous": body["previous"]}, headers=MUTATE)
    assert u.status_code == 200
    row = _classification(ws, "tx-pix-out")
    assert (row["category_id"], row["source"], row["confidence"]) == ("shopping", "pluggy_map", 0.7)


def test_confirm_uncategorized_then_undo_deletes(api):
    ws = _ws(api)
    body = api.post(f"{URL}/tx-pix-in/confirm", json={"category_id": "services_nf", "note": " cliente "},
                    headers=MUTATE).json()
    assert body["previous"] is None
    assert ws.conn.execute("SELECT note FROM transaction_notes WHERE transaction_id = 'tx-pix-in'").fetchone()[0] == "cliente"
    api.post(f"{URL}/tx-pix-in/undo", json={"previous": None}, headers=MUTATE)
    assert _classification(ws, "tx-pix-in") is None


def test_double_confirm_keeps_first_previous_valid(api):
    ws = _ws(api)
    first = api.post(f"{URL}/tx-pix-out/confirm", json={"category_id": "groceries"}, headers=MUTATE).json()
    second = api.post(f"{URL}/tx-pix-out/confirm", json={"category_id": "groceries"}, headers=MUTATE).json()
    assert second["previous"]["source"] == "manual"
    api.post(f"{URL}/tx-pix-out/undo", json={"previous": first["previous"]}, headers=MUTATE)
    row = _classification(ws, "tx-pix-out")
    assert (row["category_id"], row["source"]) == ("shopping", "pluggy_map")


def test_confirm_unknown_category_or_tx(api):
    assert api.post(f"{URL}/tx-pix-out/confirm", json={"category_id": "zzz"}, headers=MUTATE).status_code == 422
    assert api.post(f"{URL}/nope/confirm", json={"category_id": "groceries"}, headers=MUTATE).status_code == 404


def test_confirm_with_rule_never_writes_cpf(api):
    ws = _ws(api)
    cpf = "12345678901"
    ws.conn.execute("UPDATE transactions SET counterparty_doc = ?, counterparty_name = 'MARIA SILVA' "
                    "WHERE id = 'tx-pix-in'", (cpf,))
    ws.conn.commit()
    body = api.post(f"{URL}/tx-pix-in/confirm", json={"category_id": "services_nf", "create_rule": True},
                    headers=MUTATE).json()
    assert body["rule_id"]
    text = ws.rules_path.read_text()
    assert not re.search(r"\d{11}", text)
    assert body["rule_id"] in text and "MARIA SILVA" in text


def test_create_rule_endpoint(api):
    ws = _ws(api)
    r = api.post("/api/v1/rules", json={"transaction_id": "tx-pix-in", "category_id": "services_nf"}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["rule_id"] in ws.rules_path.read_text()
    assert api.post("/api/v1/rules", json={"transaction_id": "nope", "category_id": "services_nf"},
                    headers=MUTATE).status_code == 404


def test_stale_helper_never_compiles(api, monkeypatch, tmp_path):
    helper, src = tmp_path / "fm-classify", tmp_path / "main.swift"
    helper.write_text("x")
    src.write_text("y")
    import os
    os.utime(helper, (1, 1))  # older than the source = stale
    monkeypatch.setattr(llm, "HELPER_BIN", helper)
    monkeypatch.setattr(llm, "HELPER_SRC", src)
    calls = []
    monkeypatch.setattr(llm, "ensure_helper", lambda: calls.append("compile"))
    monkeypatch.setattr(llm, "run_helper", lambda reqs: calls.append("run") or {})
    ws = _ws(api)
    assert llm.suggest(ws.conn, ws.taxonomy, [], [], compile=False) == {}
    from finance.api.routes import review
    review._suggest_in_background(str(tmp_path / "api.db"), ws.taxonomy, {"tx-pix-in"})
    assert api.get(URL).status_code == 200
    assert calls == []


def test_rule_without_matcher_is_refused_and_nothing_changes(api):
    ws = _ws(api)
    ws.conn.execute("UPDATE transactions SET counterparty_name = NULL, counterparty_doc = NULL, description = '' "
                    "WHERE id = 'tx-pix-in'")
    ws.conn.commit()
    before = ws.rules_path.read_text()
    r = api.post(f"{URL}/tx-pix-in/confirm", json={"category_id": "services_nf", "create_rule": True}, headers=MUTATE)
    assert r.status_code == 422
    assert ws.rules_path.read_text() == before
    assert _classification(ws, "tx-pix-in") is None
    assert api.post("/api/v1/rules", json={"transaction_id": "tx-pix-in", "category_id": "services_nf"},
                    headers=MUTATE).status_code == 422


def test_failed_rule_leaves_no_manual_classification(api, monkeypatch):
    from finance.api.routes import review
    ws = _ws(api)

    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(review, "classify_all", boom)
    with pytest.raises(RuntimeError):
        api.post(f"{URL}/tx-pix-in/confirm", json={"category_id": "services_nf", "note": "n", "create_rule": True},
                 headers=MUTATE)
    assert _classification(ws, "tx-pix-in") is None
    assert ws.conn.execute("SELECT 1 FROM transaction_notes WHERE transaction_id = 'tx-pix-in'").fetchone() is None


def test_transfer_detector_item_suggests_its_current_category(api):
    ws = _ws(api)
    ws.conn.execute("UPDATE classifications SET confidence = 0.5 WHERE transaction_id = 'tx-bill-pay'")
    ws.conn.execute("INSERT INTO llm_suggestions (transaction_id, category_id, prompt_version, created_at) "
                    "VALUES ('tx-bill-pay', 'groceries', ?, 'x')", (llm.PROMPT_VERSION,))
    ws.conn.commit()
    item = next(i for i in api.get(URL).json() if i["id"] == "tx-bill-pay")
    assert item["suggestion"] == {"category_id": "card_bill_payment", "reason": "transfer",
                                  "detail": "Detectado como transferência"}


def test_low_confidence_current_category_beats_model(api):
    ws = _ws(api)
    ws.conn.execute("UPDATE classifications SET confidence = 0.5 WHERE transaction_id = 'tx-pix-out'")
    ws.conn.execute("INSERT INTO llm_suggestions (transaction_id, category_id, prompt_version, created_at) "
                    "VALUES ('tx-pix-out', 'housing', ?, 'x')", (llm.PROMPT_VERSION,))
    ws.conn.commit()
    assert _classification(ws, "tx-pix-out")["source"] == "pluggy_map"
    item = next(i for i in api.get(URL).json() if i["id"] == "tx-pix-out")
    assert item["suggestion"] == {"category_id": "shopping", "reason": "current",
                                  "detail": "Categoria atual (confiança baixa)"}
