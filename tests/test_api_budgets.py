from api_fixtures import MUTATE

URL = "/api/v1/budgets"


def test_put_get_delete_budget(api):
    assert api.get(URL).json() == {}
    assert api.put(f"{URL}/groceries", json={"monthly_amount": 1500.5}, headers=MUTATE).status_code == 200
    assert api.put(f"{URL}/groceries", json={"monthly_amount": 1600}, headers=MUTATE).status_code == 200
    assert api.get(URL).json() == {"groceries": 1600}
    assert api.delete(f"{URL}/groceries", headers=MUTATE).status_code == 204
    assert api.get(URL).json() == {}


def test_budget_rejects_income_category(api):
    r = api.put(f"{URL}/salary", json={"monthly_amount": 10}, headers=MUTATE)
    assert r.status_code == 422
    assert api.put(f"{URL}/nope", json={"monthly_amount": 10}, headers=MUTATE).status_code == 422
    assert api.get(URL).json() == {}


def test_budget_rejects_zero(api):
    for amount in (0, -5):
        assert api.put(f"{URL}/groceries", json={"monthly_amount": amount}, headers=MUTATE).status_code == 422
