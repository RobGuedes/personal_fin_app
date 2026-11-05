from api_fixtures import MUTATE
from finance.classify import classify_all
from samples import MY_CPF

URL = "/api/v1/transactions"


def _ws(client):
    return client.app.dependency_overrides[next(iter(client.app.dependency_overrides))]()


def _items(client, **params):
    r = client.get(URL, params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_card_charge_listed_once_with_its_label(api):
    items = [i for i in _items(api, limit=100) if i["id"] == "tx-card-buy"]
    assert len(items) == 1
    assert items[0]["amount"] == -2950.4
    assert items[0]["category_label"] == "Doações"
    assert items[0]["line"] == "expenses"


def test_search_accent_insensitive(api):
    assert {i["id"] for i in _items(api, q="pagamento")} >= {"tx-bill-pay", "tx-pix-out"}
    ids = {i["id"] for i in _items(api, q="ONG exemplo cidade")}
    assert ids == {"tx-card-buy"}
    api.patch(f"{URL}/tx-pix-in", json={"note": "Reunião café"}, headers=MUTATE)
    assert [i["id"] for i in _items(api, q="REUNIAO CAFE")] == ["tx-pix-in"]


def test_search_amount(api):
    assert {i["id"] for i in _items(api, q="> 2.900,00")} == {"tx-bill-pay", "tx-card-buy", "tx-card-pay"}
    assert [i["id"] for i in _items(api, q="=512,34")] == ["tx-pix-in"]
    assert {i["id"] for i in _items(api, q="< 700")} == {"tx-pix-in"}


def test_excluded_flag_for_own_transfers(api):
    by_id = {i["id"]: i for i in _items(api, limit=100)}
    assert by_id["tx-bill-pay"]["excluded"] and by_id["tx-card-pay"]["excluded"]
    assert not by_id["tx-pix-out"]["excluded"]
    assert by_id["tx-inst-2"]["installment"] == "2/10"
    assert by_id["tx-inst-2"]["month"] == "2026-08"
    assert set(by_id["tx-pix-out"]) >= {"account", "counterparty", "method", "source", "note", "in_review"}
    assert "counterparty_doc" not in by_id["tx-pix-out"] and "raw_json" not in by_id["tx-pix-out"]


def test_filters(api):
    assert {i["id"] for i in _items(api, month="2026-08")} == {"tx-inst-2"}
    assert {i["id"] for i in _items(api, category="donations")} == {"tx-card-buy"}
    assert {i["id"] for i in _items(api, category="shopping")} == {"tx-pix-out", "tx-inst-2", "tx-inst-10"}
    assert {i["id"] for i in _items(api, method="pix")} == {"tx-pix-out", "tx-pix-in"}
    assert "tx-pix-in" in {i["id"] for i in _items(api, unreviewed="true")}
    assert "tx-card-buy" not in {i["id"] for i in _items(api, unreviewed="true")}


def test_detail_has_pair_and_pluggy_category(api):
    d = api.get(f"{URL}/tx-bill-pay").json()
    assert d["transfer_pair"]["id"] == "tx-card-pay"
    assert "suggestion" in d and "pluggy_category" in d
    assert api.get(f"{URL}/tx-pix-in").json()["transfer_pair"] is None
    assert api.get(f"{URL}/nope").status_code == 404


def test_patch_category_is_manual_and_survives_classify(api):
    r = api.patch(f"{URL}/tx-pix-in", json={"category_id": "services_nf"}, headers=MUTATE)
    assert r.status_code == 200
    body = r.json()
    assert (body["category_id"], body["source"], body["in_review"]) == ("services_nf", "manual", False)
    ws = _ws(api)
    classify_all(ws.conn, ws.taxonomy, {"rules": []}, MY_CPF)
    assert api.get(f"{URL}/tx-pix-in").json()["category_id"] == "services_nf"


def test_patch_note_and_clear(api):
    assert api.patch(f"{URL}/tx-pix-in", json={"note": "  oi "}, headers=MUTATE).json()["note"] == "oi"
    assert api.get(f"{URL}/tx-pix-in").json()["note"] == "oi"
    assert api.patch(f"{URL}/tx-pix-in", json={"note": None}, headers=MUTATE).json()["note"] is None
    api.patch(f"{URL}/tx-pix-in", json={"note": "x"}, headers=MUTATE)
    assert api.patch(f"{URL}/tx-pix-in", json={"note": ""}, headers=MUTATE).json()["note"] is None
    assert _ws(api).conn.execute("SELECT count(*) FROM transaction_notes").fetchone()[0] == 0


def test_patch_requires_header(api):
    assert api.patch(f"{URL}/tx-pix-in", json={"note": "x"}).status_code == 403


def test_unknown_category_422(api):
    assert api.patch(f"{URL}/tx-pix-in", json={"category_id": "nope"}, headers=MUTATE).status_code == 422
    assert api.patch(f"{URL}/nope", json={"note": "x"}, headers=MUTATE).status_code == 404


def test_pagination_cursor_stable(api):
    full = [i["id"] for i in _items(api, limit=100)]
    seen, cursor = [], None
    while True:
        params = {"limit": 3, **({"cursor": cursor} if cursor else {})}
        body = api.get(URL, params=params).json()
        seen += [i["id"] for i in body["items"]]
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert seen == full and len(set(seen)) == len(seen) == 7


def test_search_matches_account_label(api):
    ids = {i["id"] for i in _items(api, q="exemplo visa")}
    assert ids == {"tx-card-buy", "tx-card-pay", "tx-inst-2", "tx-inst-10"}
    assert {i["id"] for i in _items(api, q="itau 7890")} == {"tx-pix-out", "tx-pix-in", "tx-bill-pay"}
