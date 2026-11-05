import pytest

from finance.search import parse_query


@pytest.mark.parametrize("q,op,amount", [("> 1.600,00", ">", 1600.0), ("=1600", "=", 1600.0),
                                         ("< 99,9", "<", 99.9), (">1600.50", ">", 1600.5), ("> 1.600", ">", 1600.0)])
def test_amount_formats(q, op, amount):
    r = parse_query(q)
    assert (r.op, r.amount, r.text) == (op, amount, "")


def test_text_is_folded():
    r = parse_query("Café")
    assert (r.text, r.op, r.amount) == ("cafe", None, None)


def test_text_with_amount():
    r = parse_query("Mercado > 50")
    assert (r.text, r.op, r.amount) == ("mercado", ">", 50.0)
