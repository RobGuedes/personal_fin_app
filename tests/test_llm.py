import json
import subprocess

import pytest

from finance import llm
from finance.classify import UNCATEGORIZED, load_taxonomy
from finance.db import connect
from samples import CATEGORIES_FIXTURE

TAX = load_taxonomy(CATEGORIES_FIXTURE)


def tx(id, description, amount, category=UNCATEGORIZED, source=None, rule_id=None, date="2026-10-01"):
    return {"id": id, "description": description, "amount": amount, "category_id": category, "source": source,
            "rule_id": rule_id, "date": date, "payment_method": "pix", "counterparty_name": None,
            "merchant_name": None, "pluggy_category": "Services", "confidence": 1.0 if source else None,
            "line": TAX.line_of(category) or ("expenses" if amount < 0 else "income")}


def test_allowed_categories_follow_direction():
    out = llm.allowed_categories("out", TAX)
    inn = llm.allowed_categories("in", TAX)
    assert "groceries" in out.values() and "donations" in out.values() and "dividends" not in out.values()
    assert "dividends" in inn.values() and "groceries" not in inn.values()
    assert out[llm.UNSURE] == UNCATEGORIZED
    assert "own_transfer" not in out.values()  # excluded/investment lines are the detector's job


def test_similar_examples_share_words_same_direction_and_skip_generic_words():
    labeled = [tx("a", "Compra débito Padaria Bom Pao", -10, "restaurants", "manual"),
               tx("b", "Pix recebido PADARIA BOM PAO", 10, "other_income", "rule"),
               tx("c", "Pix enviado FULANO", -10, "gifts", "rule")]
    got = llm.similar_examples(tx("q", "Compra débito Padaria Central", -5), labeled)
    assert [e["id"] for e in got] == ["a"]  # "pix/compra/debito" don't count as shared words
    assert llm.similar_examples(tx("q", "Compra débito Padaria", -5), labeled, exclude_rule=None)[0]["id"] == "a"
    assert llm.similar_examples(tx("q", "Padaria", -5), [labeled[0] | {"rule_id": "r"}], exclude_rule="r") == []


def test_build_request_uses_labels_and_examples():
    labeled = [tx("a", "Compra débito Padaria Bom Pao", -10, "restaurants", "manual")]
    req = llm.build_request(tx("q", "Compra débito Padaria Central", -18.45), TAX, labeled)
    assert "Restaurants & delivery" in req["categories"] and llm.UNSURE in req["categories"]
    assert "R$ 18.45 paid" in req["prompt"]
    assert "- Compra débito Padaria Bom Pao -> Restaurants & delivery" in req["prompt"]


def test_run_helper_maps_labels_back_and_treats_unsure_as_none(monkeypatch):
    reqs = [llm.build_request(tx("q1", "Posto", -100), TAX, []), llm.build_request(tx("q2", "Pix", -5), TAX, [])]
    monkeypatch.setattr(llm, "ensure_helper", lambda: None)

    def fake_run(cmd, input, capture_output, text):
        sent = [json.loads(line) for line in input.splitlines()]
        assert all("_allowed" not in s for s in sent)
        out = [{"id": "q1", "category": "Transport & fuel"}, {"id": "q2", "category": llm.UNSURE}]
        return subprocess.CompletedProcess(cmd, 0, "\n".join(json.dumps(o) for o in out), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert llm.run_helper(reqs) == {"q1": "transport", "q2": None}


def test_unavailable_model_raises(monkeypatch):
    monkeypatch.setattr(llm, "ensure_helper", lambda: None)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 2, "", "unavailable"))
    with pytest.raises(RuntimeError, match="unavailable"):
        llm.run_helper([llm.build_request(tx("q", "x", -1), TAX, [])])


def test_suggest_stores_once_per_prompt_version(tmp_path, monkeypatch):
    from finance.sync import sync
    from test_sync import TODAY, FakeClient

    conn = connect(tmp_path / "t.db")
    sync(conn, FakeClient(), ["item-1"], today=TODAY)
    calls = []
    monkeypatch.setattr(llm, "run_helper", lambda reqs: calls.append(len(reqs)) or {r["id"]: "gifts" for r in reqs})
    queue = [tx("tx-pix-in", "Pix recebido", 512.34)]
    llm.suggest(conn, TAX, queue, [])
    llm.suggest(conn, TAX, queue, [])
    assert calls == [1, 0]
    assert llm.stored_suggestions(conn) == {"tx-pix-in": "gifts"}
    # suggestions never touch classifications
    assert conn.execute("SELECT COUNT(*) FROM classifications").fetchone()[0] == 0


def test_transfer_detector_items_are_not_sent(tmp_path, monkeypatch):
    conn = connect(tmp_path / "t.db")
    sent = []
    monkeypatch.setattr(llm, "run_helper", lambda reqs: sent.extend(r["id"] for r in reqs) or {})
    queue = [tx("a", "Pix enviado EU MESMO", -100) | {"source": "transfer_detector", "category_id": "own_transfer"},
             tx("b", "Pix enviado LOJA", -50)]
    llm.suggest(conn, TAX, queue, [])
    assert sent == ["b"]
