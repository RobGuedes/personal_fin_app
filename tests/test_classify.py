import pytest

from finance.aggregate import coverage, ledger, review_queue
from finance.classify import (
    Rule,
    append_rule,
    classify_all,
    load_rules_config,
    load_taxonomy,
    parse_rules,
    rule_matches,
    set_manual,
)
from finance.db import connect
from finance.sync import sync
from samples import CATEGORIES_FIXTURE, MY_CPF, RULES_FIXTURE
from test_sync import TODAY, FakeClient

ACCOUNT = {"name": "BTG Investimentos", "number_masked": "*****0001"}


def tx(**kw):
    base = {"description": "", "description_raw": "", "amount_normalized": -10.0, "payment_method": "pix",
            "counterparty_name": None, "counterparty_doc": None, "merchant_name": None}
    return {**base, **kw}


def rule(**conditions):
    return Rule("r", "groceries", 0, 1.0, conditions)


def test_example_config_files_load():
    from finance.config import CONFIG_DIR
    taxonomy = load_taxonomy(CONFIG_DIR / "categories.example.yaml")
    rules = parse_rules(load_rules_config(CONFIG_DIR / "rules.example.yaml"), taxonomy)
    assert rules
    assert taxonomy.line_of("groceries") == "expenses"
    assert taxonomy.line_of("data_error") == "excluded"
    assert all(r.category in taxonomy.categories for r in rules)


@pytest.mark.parametrize("conditions, transaction, expected", [
    ({"description": "mercado"}, tx(description="AME MERCADO EXEMP"), True),
    ({"description": "mercado"}, tx(description="X", description_raw="MERCADO"), True),
    ({"description": "mercado"}, tx(description="FARMACIA"), False),
    ({"counterparty_name": "^EMPRESA Y"}, tx(counterparty_name="EMPRESA Y LTDA"), True),
    ({"counterparty_doc": ["12.345.678/0001-90"]}, tx(counterparty_doc="12345678000190"), True),
    ({"counterparty_doc": "123"}, tx(counterparty_doc=None), False),
    ({"merchant": "uber"}, tx(merchant_name="UBER *TRIP"), True),
    ({"party": "pessoa a"}, tx(description="ENVIO TRANSFERÊNCIA", counterparty_name="Pessoa A"), True),
    ({"party": "pessoa c"}, tx(description="Pix enviado PESSOA C"), True),
    ({"party": "mercado pago"}, tx(merchant_name="MERCADO PAGO LTDA"), True),
    ({"party": "pessoa a"}, tx(description="Pix enviado PESSOA C"), False),
    ({"account": "BTG"}, tx(), True),
    ({"account": "0001"}, tx(), True),
    ({"account": "itau"}, tx(), False),
    ({"direction": "in"}, tx(amount_normalized=5.0), True),
    ({"direction": "in"}, tx(amount_normalized=-5.0), False),
    ({"amount_min": 100, "amount_max": 200}, tx(amount_normalized=-150.0), True),
    ({"amount_min": 100}, tx(amount_normalized=-50.0), False),
    ({"payment_method": ["pix", "ted_doc"]}, tx(payment_method="pix"), True),
    ({"payment_method": "card"}, tx(payment_method="pix"), False),
    ({"description": "TAXA", "direction": "in"}, tx(description="TAXA DE CARTEIRA ADM", amount_normalized=-1.0), False),
])
def test_rule_conditions(conditions, transaction, expected):
    assert rule_matches(rule(**conditions), transaction, ACCOUNT) is expected


def test_rules_sorted_by_priority_then_file_order():
    taxonomy = load_taxonomy(CATEGORIES_FIXTURE)
    rules = parse_rules({"rules": [
        {"id": "a", "description": "x", "category": "groceries"},
        {"id": "b", "description": "x", "category": "shopping", "priority": 5},
        {"id": "c", "description": "x", "category": "travel"},
    ]}, taxonomy)
    assert [r.id for r in rules] == ["b", "a", "c"]


def test_unknown_category_in_rule_is_rejected():
    with pytest.raises(ValueError, match="unknown category"):
        parse_rules({"rules": [{"id": "x", "category": "nope"}]}, load_taxonomy(CATEGORIES_FIXTURE))


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    sync(c, FakeClient(), ["item-1"], today=TODAY)
    yield c
    c.close()


def classified(conn):
    return {r["transaction_id"]: (r["category_id"], r["source"])
            for r in conn.execute("SELECT * FROM classifications")}


def test_pipeline_order_and_bill_payment_excluded(conn):
    taxonomy = load_taxonomy(CATEGORIES_FIXTURE)
    cfg = {"transfers": {}, "investments": {},
           "rules": [{"id": "ong", "description": "ONG EXEMPLO", "category": "donations"},
                     # would also match the bill payment, but the transfer detector runs first
                     {"id": "fatura", "description": "fatura", "category": "shopping"}]}
    classify_all(conn, taxonomy, cfg, MY_CPF)
    got = classified(conn)
    assert got["tx-bill-pay"] == ("card_bill_payment", "transfer_detector")
    assert got["tx-card-pay"] == ("card_bill_payment", "transfer_detector")
    assert got["tx-card-buy"] == ("donations", "rule")
    assert got["tx-pix-out"] == ("shopping", "pluggy_map")
    assert "tx-pix-in" not in got  # "Transfer - PIX" is not mapped -> uncategorized

    rows = {r["id"]: r for r in ledger(conn, taxonomy)}
    assert rows["tx-bill-pay"]["line"] == rows["tx-card-pay"]["line"] == "excluded"
    # installment counts in its bill month, not its purchase date
    assert rows["tx-inst-2"]["month"] == "2026-08"


def test_manual_wins_and_survives_reclassification(conn):
    taxonomy = load_taxonomy(CATEGORIES_FIXTURE)
    set_manual(conn, "tx-pix-out", "gifts", taxonomy)
    classify_all(conn, taxonomy, {}, MY_CPF)
    classify_all(conn, taxonomy, {}, MY_CPF)
    assert classified(conn)["tx-pix-out"] == ("gifts", "manual")
    with pytest.raises(ValueError):
        set_manual(conn, "tx-pix-out", "nope", taxonomy)


def test_manual_saved_during_classify_wins(conn, monkeypatch, tmp_path):
    """A manual classification saved while classify runs (after its first read) must not fail the run."""
    import finance.classify as classify_mod

    taxonomy = load_taxonomy(CATEGORIES_FIXTURE)
    real_detect = classify_mod.detect

    def detect_then_user_saves(*a, **k):
        out = real_detect(*a, **k)
        set_manual(conn, "tx-bill-pay", "gifts", taxonomy)  # a detector-classified row
        set_manual(conn, "tx-pix-out", "gifts", taxonomy)
        return out

    monkeypatch.setattr(classify_mod, "detect", detect_then_user_saves)
    counts = classify_all(conn, taxonomy, {}, MY_CPF)
    got = classified(conn)
    assert got["tx-bill-pay"] == ("gifts", "manual")
    assert got["tx-pix-out"] == ("gifts", "manual")
    assert counts["manual"] == 2
    linked = {r[0] for r in conn.execute("SELECT from_transaction_id FROM transfer_links "
                                        "UNION SELECT to_transaction_id FROM transfer_links")}
    assert "tx-bill-pay" not in linked


def test_data_error_is_excluded(conn):
    taxonomy = load_taxonomy(CATEGORIES_FIXTURE)
    set_manual(conn, "tx-pix-in", "data_error", taxonomy)
    classify_all(conn, taxonomy, {}, MY_CPF)
    row = next(r for r in ledger(conn, taxonomy) if r["id"] == "tx-pix-in")
    assert row["line"] == "excluded"


def test_coverage_and_review_queue(conn):
    taxonomy = load_taxonomy(CATEGORIES_FIXTURE)
    classify_all(conn, taxonomy, {}, MY_CPF)
    rows = ledger(conn, taxonomy)
    cov = coverage(rows, ["2026-10"])
    # Oct P&L outflows: pix-out 1765.43 (shopping) + card-buy 2950.40 (Pluggy "Donations")
    assert cov["count"] == 2 and cov["pct_value"] == 100.0
    queue_ids = {r["id"] for r in review_queue(rows, 0.6)}
    assert "tx-pix-in" in queue_ids and "tx-pix-out" not in queue_ids


# --- Binance rules (real config) ---
BINANCE = {"name": "Binance", "number_masked": None}


def _first_rule(transaction, account=BINANCE):
    rules = parse_rules(load_rules_config(RULES_FIXTURE), load_taxonomy(CATEGORIES_FIXTURE))
    return next((r.id for r in rules if rule_matches(r, transaction, account)), None)


def _btx(description, amount):
    return tx(description=description, amount_normalized=amount, payment_method="other")


def test_foreign_client_deposit_rule():
    assert _first_rule(_btx("Binance deposit USDT (TRX)", 2468.10)) == "cliente_exterior"


def test_two_month_foreign_client_deposit_rule():
    assert _first_rule(_btx("Binance deposit USDT (TRX)", 4936.20)) == "cliente_exterior"


def test_small_deposit_has_no_rule():
    assert _first_rule(_btx("Binance deposit USDT (TRX)", 50)) is None


@pytest.mark.parametrize("tail", ["9001", "9002"])
def test_card_wallet_withdrawal_rule(tail):
    assert _first_rule(_btx(f"Binance withdrawal USDT (BSC) → …{tail}", -1200)) == "carteira_exemplo"


def test_unknown_address_has_no_rule():
    assert _first_rule(_btx("Binance withdrawal USDT (BSC) → …9999", -1200)) is None


def test_fiat_and_earn_rules():
    assert _first_rule(_btx("Binance BRL deposit", 500)) == "binance_fiat"
    assert _first_rule(_btx("Binance BRL withdrawal", -500)) == "binance_fiat"
    assert _first_rule(_btx("Binance Earn interest USDT 2026-10", 1.2)) == "binance_earn"


def test_binance_pix_bank_side_rule():
    t = tx(description="Pix enviado", counterparty_name="BINANCE BRASIL", amount_normalized=-300)
    assert _first_rule(t, ACCOUNT) == "binance_pix"


def test_services_abroad_is_income_without_nf():
    c = load_taxonomy(CATEGORIES_FIXTURE).categories["services_abroad"]
    assert c["line"] == "income" and not c.get("nf_issued")


def _binance_rows(conn, rate):
    from binance_samples import REWARD_D1, WITHDRAWAL
    from finance import binance_normalize as bn
    from finance.binance_sync import upsert_row
    from finance.sync import _upsert
    with conn:
        _upsert(conn, "items", bn.item_row("2026-11-01T00:00:00+00:00"))
        _upsert(conn, "accounts", bn.account_row(None))
        rows = bn.earn_rows([{**REWARD_D1, "asset": "OPN"}, REWARD_D1], [], rate)
        rows.append(bn.withdrawal_row({**WITHDRAWAL, "id": "FAKEWD0000000000000000000000009",
                                       "address": "0xFAKE0000000000000000000000000000000009001"}, rate))
        for r in rows:
            upsert_row(conn, r, "2026-11-01T00:00:00+00:00")


def test_unpriced_binance_rows_capped_at_review_confidence(conn):
    taxonomy = load_taxonomy(CATEGORIES_FIXTURE)
    _binance_rows(conn, lambda a, d: 5.0 if a == "USDT" else None)
    classify_all(conn, taxonomy, load_rules_config(RULES_FIXTURE), MY_CPF)
    conf = {r["transaction_id"]: (r["category_id"], r["confidence"]) for r in conn.execute(
        "SELECT * FROM classifications WHERE transaction_id LIKE 'binance:%'")}
    assert conf["binance:earn:2026-10:OPN"][1] == 0.5          # unpriced -> review
    assert conf["binance:earn:2026-10:USDT"][1] == 1.0         # priced -> untouched
    queue = {r["id"] for r in review_queue(ledger(conn, taxonomy), 0.6)}
    assert "binance:earn:2026-10:OPN" in queue and "binance:earn:2026-10:USDT" not in queue


def test_unpriced_binance_withdrawal_direction_uses_amount_sign(conn):
    taxonomy = load_taxonomy(CATEGORIES_FIXTURE)
    _binance_rows(conn, lambda a, d: None)
    classify_all(conn, taxonomy, load_rules_config(RULES_FIXTURE), MY_CPF)
    cat, conf = conn.execute("SELECT category_id, confidence FROM classifications "
                             "WHERE transaction_id = 'binance:wd:FAKEWD0000000000000000000000009'").fetchone()
    assert cat == "travel" and conf == 0.5  # carteira_exemplo needs direction 'out'; amount_normalized is 0


# --- remove_rule (text-based, keeps comments) -----------------------------------------------------

RULES_TEXT = """\
transfers:
  # card bill payments
  bill_payment_max_days: 5

rules:
  # --- Binance ---
  - id: cliente_exterior
    # USD from Cliente Exterior
    category: services_abroad
    direction: in

  - id: cliente_exterior_2
    # the second one
    category: services_abroad

  # --- Income ---
  - id: "quoted_rule"
    category: dividends
    party: ICON

  - category: groceries
    id: id_not_first
    party: MERCADO
"""


def _ids(path):
    return [r.get("id") for r in load_rules_config(path)["rules"]]


@pytest.fixture
def rules_file(tmp_path):
    p = tmp_path / "rules.yaml"
    p.write_text(RULES_TEXT)
    return p


def test_remove_rule_exact_id_keeps_prefix_twin_and_comments(rules_file):
    from finance.classify import remove_rule
    assert remove_rule("cliente_exterior", rules_file, load_taxonomy(CATEGORIES_FIXTURE)) is True
    text = rules_file.read_text()
    assert _ids(rules_file) == ["cliente_exterior_2", "quoted_rule", "id_not_first"]
    assert "# USD from Cliente Exterior" not in text           # the block's own comment goes with it
    for kept in ("# card bill payments", "# --- Binance ---", "# the second one", "# --- Income ---"):
        assert kept in text
    assert "\n\n\n" not in text


def test_remove_rule_before_section_comment_keeps_it(rules_file):
    from finance.classify import remove_rule
    assert remove_rule("cliente_exterior_2", rules_file, load_taxonomy(CATEGORIES_FIXTURE))
    text = rules_file.read_text()
    assert _ids(rules_file) == ["cliente_exterior", "quoted_rule", "id_not_first"]
    assert "# the second one" not in text and "# --- Income ---" in text
    assert text.index("direction: in") < text.index("# --- Income ---") < text.index("quoted_rule")


def test_remove_rule_quoted_and_id_not_first_and_last(rules_file):
    from finance.classify import remove_rule
    tax = load_taxonomy(CATEGORIES_FIXTURE)
    assert remove_rule("quoted_rule", rules_file, tax)
    assert remove_rule("id_not_first", rules_file, tax)
    assert _ids(rules_file) == ["cliente_exterior", "cliente_exterior_2"]
    assert rules_file.read_text().endswith("category: services_abroad\n\n  # --- Income ---\n")


def test_remove_rule_absent_returns_false_and_leaves_file(rules_file):
    from finance.classify import remove_rule
    assert remove_rule("cliente", rules_file, load_taxonomy(CATEGORIES_FIXTURE)) is False
    assert remove_rule("nope", rules_file, load_taxonomy(CATEGORIES_FIXTURE)) is False
    assert rules_file.read_text() == RULES_TEXT


def test_remove_rule_restores_file_when_result_is_invalid(tmp_path):
    from finance.classify import remove_rule
    p = tmp_path / "rules.yaml"
    # A column-0 comment ends the block early: the orphaned keys make the result invalid.
    original = "rules:\n  - id: a\n# odd comment\n    category: groceries\n  - id: b\n    category: groceries\n"
    p.write_text(original)
    with pytest.raises(ValueError):
        remove_rule("a", p, load_taxonomy(CATEGORIES_FIXTURE))
    assert p.read_text() == original


def test_remove_rule_on_example_rules_copy(tmp_path):
    import shutil

    from finance.classify import remove_rule
    from finance.config import CONFIG_DIR
    p = tmp_path / "rules.yaml"
    shutil.copy(CONFIG_DIR / "rules.example.yaml", p)
    before = _ids(p)
    for target in (before[0], before[-1]):  # remove_rule must cope with the shipped layout (groups, comments)
        assert remove_rule(target, p, load_taxonomy(CATEGORIES_FIXTURE))
        assert target not in _ids(p)
    assert _ids(p) == before[1:-1]
    assert load_rules_config(p)["transfers"] == load_rules_config(CONFIG_DIR / "rules.example.yaml")["transfers"]


# --- config/*.yaml missing: fall back to the committed .example templates ------------------------

def test_missing_config_reads_example(tmp_path):
    (tmp_path / "rules.example.yaml").write_text("rules: []\ntransfers: {own_transfer_window_days: 9}\n")
    assert load_rules_config(tmp_path / "rules.yaml")["transfers"]["own_transfer_window_days"] == 9
    assert not (tmp_path / "rules.yaml").exists()  # reading never creates the real file


def test_first_rule_write_copies_example_and_leaves_it_untouched(tmp_path):
    import shutil

    from finance.config import CONFIG_DIR
    example = tmp_path / "rules.example.yaml"
    shutil.copy(CONFIG_DIR / "rules.example.yaml", example)
    original = example.read_text()
    real = tmp_path / "rules.yaml"
    rule_id = append_rule({"id": "new_rule", "party": "LOJA NOVA", "direction": "out", "category": "shopping"},
                          load_taxonomy(CATEGORIES_FIXTURE), real)
    assert rule_id == "new_rule" and "LOJA NOVA" in real.read_text()
    assert real.read_text().startswith(original.rstrip("\n"))
    assert example.read_text() == original


def test_real_config_wins_over_example(tmp_path):
    (tmp_path / "rules.example.yaml").write_text("transfers: {own_transfer_window_days: 9}\n")
    (tmp_path / "rules.yaml").write_text("transfers: {own_transfer_window_days: 1}\n")
    assert load_rules_config(tmp_path / "rules.yaml")["transfers"]["own_transfer_window_days"] == 1


# --- rules.yaml writes: concurrency and injection ---------------------------------------------------

def test_concurrent_rule_writes_keep_every_rule(rules_file):
    """Simultaneous saves (double click, two tabs) must not lose rules or leave a truncated file."""
    import threading

    from finance.classify import append_rule, remove_rule
    tax = load_taxonomy(CATEGORIES_FIXTURE)
    n = 12
    barrier = threading.Barrier(n + 2)
    bad_reads: list = []
    stop = threading.Event()

    def writer(i):
        barrier.wait()
        append_rule({"id": f"race_{i}", "category": "groceries", "party": f"LOJA {i}"}, tax, rules_file)

    def remover():
        barrier.wait()
        remove_rule("cliente_exterior_2", rules_file, tax)

    def reader():
        barrier.wait()
        while not stop.is_set():
            try:
                if len(load_rules_config(rules_file).get("rules") or []) < 3:
                    bad_reads.append("short")
            except Exception as e:  # a half-written file
                bad_reads.append(type(e).__name__)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(n)] + [threading.Thread(target=remover)]
    r = threading.Thread(target=reader)
    r.start()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop.set()
    r.join()
    ids = _ids(rules_file)
    assert sorted(i for i in ids if i.startswith("race_")) == sorted(f"race_{i}" for i in range(n))
    assert "cliente_exterior_2" not in ids and {"cliente_exterior", "quoted_rule", "id_not_first"} <= set(ids)
    assert bad_reads == []


@pytest.mark.parametrize("brk", ["\n", "\r", "\x85", " ", " "])
def test_rule_comment_cannot_inject_yaml(rules_file, brk):
    """The comment is a bank-supplied merchant name: a line break in it must not become live YAML."""
    from finance.classify import append_rule
    evil = f"ACME{brk}    category: data_error{brk}    party: .{brk}  - id: tail{brk}    category: data_error"
    rule_id = append_rule({"id": "acme", "category": "groceries", "party": "ACME", "comment": evil},
                          load_taxonomy(CATEGORIES_FIXTURE), rules_file)
    rules = {r["id"]: r for r in load_rules_config(rules_file)["rules"]}
    assert rule_id == "acme"
    assert rules["acme"]["category"] == "groceries" and rules["acme"]["party"] == "ACME"
    assert "tail" not in rules
    assert any(line.strip().startswith("# ACME") for line in rules_file.read_text().splitlines())


def test_invalid_rule_never_touches_the_file(rules_file):
    from finance.classify import append_rule
    before, mtime = rules_file.read_bytes(), rules_file.stat().st_mtime_ns
    with pytest.raises(ValueError):
        append_rule({"id": "bad", "category": "no_such_category", "party": "X"}, load_taxonomy(CATEGORIES_FIXTURE), rules_file)
    assert rules_file.read_bytes() == before
    assert rules_file.stat().st_mtime_ns == mtime  # validated in memory: never written, not "restored"
