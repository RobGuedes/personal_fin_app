from finance.transfers import detect, fold, name_matcher

MY_CPF = "11122233344"
TYPES = {"itau": "BANK", "xp_digital": "BANK", "xp_invest": "BANK", "card": "CREDIT"}
TRANSFER_CFG = {"card_payment_window_days": 3, "own_transfer_window_days": 2,
                "own_account_patterns": ["conta digital", "conta investimento"]}
INVEST_CFG = {"pluggy_categories": ["Investments"], "operation_types": ["APLICACAO_FINANCEIRA"],
              "description_patterns": ["APLICA[CÇ][AÃ]O", "RESGATE", "conta investimento"],
              "exclude_patterns": ["^IRRF", "RENDIMENTO"]}


def tx(id, account, date, amount, description="", method="other", doc=None, name=None, pluggy=None, op=None):
    return {"id": id, "account_id": account, "date": date, "amount_normalized": amount, "description": description,
            "description_raw": description, "payment_method": method, "counterparty_doc": doc,
            "counterparty_name": name, "pluggy_category": pluggy, "operation_type": op}


def run(txs):
    detections, links = detect(txs, TYPES, {MY_CPF}, ["Fulano de Tal Silva"], TRANSFER_CFG, INVEST_CFG)
    return {d.transaction_id: (d.category_id, d.confidence) for d in detections}, links


def test_fold_and_name_match_on_truncated_description():
    assert fold("  JOÃO  Ação ") == "joao acao"
    is_me = name_matcher(["Fulano de Tal Silva"])
    assert is_me("Pix recebido de Fulano De Tal Si")
    assert not is_me("Pix recebido de Fulano Souza")


def test_card_bill_payment_pairs_bank_debit_with_card_credit_a_day_apart():
    got, links = run([
        tx("bank", "itau", "2026-10-21", -3210.0, "Pagamento de fatura Fatura Paga Cartao Exemplo"),
        tx("card", "card", "2026-10-20", 3210.0, "PAGAMENTO COM SALDO"),
    ])
    assert got == {"bank": ("card_bill_payment", 1.0), "card": ("card_bill_payment", 1.0)}
    assert [(l.from_id, l.to_id, l.link_type) for l in links] == [("bank", "card", "card_bill_payment")]


def test_card_bill_payment_prefers_a_debit_from_the_cards_own_bank():
    # Same day: a Pix from Itau to my Inter account and Inter paying its card bill, same amount.
    txs = [
        tx("itau_pix", "itau", "2026-06-09", -198.70, "Pix enviado Fulano de Tal Silva", method="pix"),
        tx("inter_in", "inter", "2026-06-09", 198.70, "Pix recebido - Fulano de Tal Silva", method="pix"),
        tx("inter_bill", "inter", "2026-06-09", -198.70, "Pagamento efetuado - Pagamento Fatura", method="boleto"),
        tx("card", "inter_card", "2026-06-09", 198.70, "PAGAMENTO ON LINE"),
    ]
    types = {**TYPES, "inter": "BANK", "inter_card": "CREDIT"}
    items = {"itau": "item-itau", "inter": "item-inter", "inter_card": "item-inter"}
    detections, links = detect(txs, types, {MY_CPF}, ["Fulano de Tal Silva"], TRANSFER_CFG, INVEST_CFG, items)
    assert {(l.from_id, l.to_id, l.link_type) for l in links} == {
        ("inter_bill", "card", "card_bill_payment"), ("itau_pix", "inter_in", "own_transfer")}
    assert all(d.confidence == 1.0 for d in detections)


def test_card_purchase_and_refund_are_not_bill_payments():
    got, _ = run([tx("buy", "card", "2026-10-02", -50.0, "LOJA", method="card"),
                  tx("refund", "card", "2026-10-05", 50.0, "LOJA ESTORNO", method="card")])
    assert got == {}


def test_unmatched_card_payment_goes_to_review():
    got, links = run([tx("card", "card", "2026-10-08", 5432.10, "Pagamento recebido")])
    assert got == {"card": ("card_bill_payment", 0.5)}
    assert links[0].to_id is None


def test_own_transfer_paired_by_cpf():
    got, _ = run([
        tx("out", "itau", "2026-10-21", -9000.0, "Pix enviado", method="pix", doc=MY_CPF),
        tx("in", "xp_digital", "2026-10-22", 9000.0, "Pix recebido", method="pix"),
    ])
    assert got == {"out": ("own_transfer", 1.0), "in": ("own_transfer", 1.0)}


def test_same_amount_without_own_signal_is_not_a_transfer():
    got, _ = run([
        tx("out", "itau", "2026-10-21", -500.0, "Pix enviado LOJA", method="pix", doc="99888777000165"),
        tx("in", "xp_digital", "2026-10-21", 500.0, "Pix recebido CLIENTE", method="pix", doc="12345678000190"),
    ])
    assert got == {}


def test_outside_window_is_not_paired():
    got, _ = run([
        tx("out", "itau", "2026-10-01", -9000.0, "Pix enviado", method="pix", doc=MY_CPF),
        tx("in", "xp_digital", "2026-10-05", 9000.0, "Pix recebido", method="pix", doc=MY_CPF),
    ])
    assert got == {"out": ("own_transfer", 0.5), "in": ("own_transfer", 0.5)}


def test_chain_through_two_accounts_pairs_pix_with_pix():
    # Itaú -Pix-> XP digital -> XP investment account -> fund. Same amount appears four times.
    got, links = run([
        tx("itau_out", "itau", "2025-12-30", -70000.0, "Pagamento de Pix QR Code FULANO DE TAL SILVA", method="pix"),
        tx("xp_dig_in", "xp_digital", "2025-12-30", 70000.0, "Pix recebido de Fulano de Tal Silva", method="pix"),
        tx("xp_dig_out", "xp_digital", "2025-12-30", -70000.0, "Transferência enviada para a conta investimento",
           method="ted_doc", pluggy="Same person transfer"),
        tx("xp_inv_in", "xp_invest", "2025-12-30", 70000.0, "Transferência recebida da conta digital"),
        tx("fund", "xp_invest", "2025-12-30", -70000.0, "TED APLICAÇÃO FUNDOS"),
    ])
    pairs = {(l.from_id, l.to_id) for l in links if l.link_type == "own_transfer"}
    assert pairs == {("itau_out", "xp_dig_in"), ("xp_dig_out", "xp_inv_in")}
    assert got["fund"] == ("investment_contribution", 1.0)


def test_investment_flows_by_direction_and_tax_excluded():
    got, _ = run([
        tx("apl", "itau", "2026-10-21", -25000.0, "Saída APLICACAO COFRINHOS", pluggy="Investments"),
        tx("res", "itau", "2026-01-08", 18750.25, "Resgate RESGATE CDB Cofrinhos"),
        tx("irrf", "xp_invest", "2026-01-08", -98.76, "IRRF S/RESGATE FUNDOS"),
        tx("yield", "itau", "2026-01-08", 0.01, "Rendimentos REND PAGO APLIC AUT MAIS"),
    ])
    assert got == {"apl": ("investment_contribution", 1.0), "res": ("investment_redemption", 1.0)}


def test_transfer_to_unconnected_own_account_is_low_confidence():
    got, _ = run([tx("out", "itau", "2026-06-09", -198.7, "Pix enviado FULANO DE TAL SILVA", method="pix")])
    assert got == {"out": ("own_transfer", 0.5)}
