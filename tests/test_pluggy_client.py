import httpx
import respx

from finance.config import Settings
from finance.pluggy_client import PluggyClient
from finance.probe import field_paths, mask

BASE = "https://api.pluggy.ai"


def make_client() -> PluggyClient:
    s = Settings(pluggy_client_id="id", pluggy_client_secret="secret")
    return PluggyClient(s, http=httpx.Client(base_url=BASE))


@respx.mock
def test_transactions_follow_cursor():
    respx.post(f"{BASE}/auth").respond(json={"apiKey": "k1"})
    route = respx.get(f"{BASE}/v2/transactions")
    route.side_effect = [
        httpx.Response(200, json={"results": [{"id": "a"}], "next": "?accountId=acc&after=cur%3D1"}),
        httpx.Response(200, json={"results": [{"id": "b"}], "next": None}),
    ]
    ids = [t["id"] for t in make_client().iter_transactions("acc")]
    assert ids == ["a", "b"]
    assert route.calls[1].request.url.params["after"] == "cur=1"


@respx.mock
def test_paged_endpoint_reads_all_pages():
    respx.post(f"{BASE}/auth").respond(json={"apiKey": "k1"})
    respx.get(f"{BASE}/accounts").side_effect = [
        httpx.Response(200, json={"results": [{"id": 1}], "page": 1, "totalPages": 2}),
        httpx.Response(200, json={"results": [{"id": 2}], "page": 2, "totalPages": 2}),
    ]
    assert [a["id"] for a in make_client().list_accounts("item")] == [1, 2]


@respx.mock
def test_reauthenticates_on_401():
    auth = respx.post(f"{BASE}/auth")
    auth.side_effect = [httpx.Response(200, json={"apiKey": "old"}), httpx.Response(200, json={"apiKey": "new"})]
    item = respx.get(f"{BASE}/items/x")
    item.side_effect = [httpx.Response(401), httpx.Response(200, json={"id": "x"})]
    assert make_client().get_item("x") == {"id": "x"}
    assert item.calls[1].request.headers["X-API-KEY"] == "new"


def test_mask_keeps_last_digits():
    assert mask("123.456.789-01") == "*******8901"
    assert mask("12") == "**"


def test_field_paths_skips_empty_and_nests():
    t = {"a": 1, "b": None, "c": {"d": "x", "e": ""}, "f": []}
    assert field_paths(t) == {"a", "c.d"}


def _client_with_sleeps():
    slept: list[float] = []
    s = Settings(pluggy_client_id="id", pluggy_client_secret="secret")
    return PluggyClient(s, http=httpx.Client(base_url=BASE), sleep=slept.append), slept


@respx.mock
def test_429_waits_for_rate_limit_reset_then_retries():
    respx.post(f"{BASE}/auth").respond(json={"apiKey": "k1"})
    respx.get(f"{BASE}/items/x").side_effect = [
        httpx.Response(429, headers={"RateLimit-Reset": "7"}), httpx.Response(200, json={"id": "x"})]
    client, slept = _client_with_sleeps()
    assert client.get_item("x") == {"id": "x"}
    assert slept == [7.0]


@respx.mock
def test_rate_limit_wait_is_capped():
    respx.post(f"{BASE}/auth").respond(json={"apiKey": "k1"})
    respx.get(f"{BASE}/items/x").side_effect = [
        httpx.Response(429, headers={"RateLimit-Reset": "86400"}), httpx.Response(200, json={"id": "x"})]
    client, slept = _client_with_sleeps()
    client.get_item("x")
    assert slept == [120.0]


@respx.mock
def test_5xx_backs_off_exponentially_then_gives_up():
    import pytest

    from finance.pluggy_client import MAX_RETRIES, PluggyError
    respx.post(f"{BASE}/auth").respond(json={"apiKey": "k1"})
    respx.get(f"{BASE}/items/x").respond(503)
    client, slept = _client_with_sleeps()
    with pytest.raises(PluggyError, match="gave up"):
        client.get_item("x")
    assert slept == [2.0**i for i in range(MAX_RETRIES)]


@respx.mock
def test_error_message_never_echoes_the_response_body():
    """Error text reaches the UI and sync_runs: the body could echo account data, so only status + code."""
    import pytest

    from finance.pluggy_client import PluggyError
    respx.post(f"{BASE}/auth").respond(json={"apiKey": "k1"})
    respx.get(f"{BASE}/items/x").respond(400, json={"code": 400, "message": "bad", "data": {"cpf": "11122233344"}})
    with pytest.raises(PluggyError) as e:
        make_client().get_item("x")
    assert "11122233344" not in str(e.value) and "HTTP 400" in str(e.value)


@respx.mock
def test_repeated_cursor_stops_instead_of_looping_forever():
    import pytest

    from finance.pluggy_client import PluggyError
    respx.post(f"{BASE}/auth").respond(json={"apiKey": "k1"})
    respx.get(f"{BASE}/v2/transactions").respond(json={"results": [{"id": "a"}], "next": "?after=same"})
    with pytest.raises(PluggyError, match="cursor"):
        list(make_client().iter_transactions("acc"))
