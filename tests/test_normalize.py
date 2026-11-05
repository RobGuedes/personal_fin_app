from finance.normalize import account_row, bill_row, local_date, payment_method, transaction_row
from samples import (
    BANK_BILL_PAYMENT,
    BANK_DEBIT_CARD,
    BANK_PIX_IN,
    BANK_PIX_OUT,
    BILL_OCT,
    CARD_ACCOUNT,
    CARD_BILL_PAYMENT_CREDIT,
    CARD_INSTALLMENT_FUTURE,
    CARD_INSTALLMENT_POSTED,
    CARD_PURCHASE,
    CHECKING_ACCOUNT,
    MY_CPF,
)

DUE = {"bill-oct": "2026-10-15", "bill-aug": "2026-08-17"}


def row(tx, account_type):
    return transaction_row(tx, account_type, DUE)


# --- sign normalization: inflow > 0, outflow < 0 --------------------------------------

def test_bank_amounts_keep_their_sign():
    assert row(BANK_PIX_OUT, "BANK")["amount_normalized"] == -1765.43
    assert row(BANK_PIX_IN, "BANK")["amount_normalized"] == 512.34


def test_card_purchase_becomes_outflow():
    r = row(CARD_PURCHASE, "CREDIT")
    assert r["amount"] == 2950.4 and r["amount_normalized"] == -2950.4


def test_card_payment_credit_becomes_inflow():
    assert row(CARD_BILL_PAYMENT_CREDIT, "CREDIT")["amount_normalized"] == 3210.0


def test_bill_payment_legs_cancel_out():
    bank = row(BANK_BILL_PAYMENT, "BANK")["amount_normalized"]
    card = row(CARD_BILL_PAYMENT_CREDIT, "CREDIT")["amount_normalized"]
    assert bank + card == 0


# --- dates ------------------------------------------------------------------------------

def test_utc_timestamp_converted_to_sao_paulo_day():
    assert local_date("2026-10-30T02:59:59.000Z") == "2026-10-29"
    assert local_date("2026-10-28T03:00:00.000Z") == "2026-10-28"
    assert local_date("2026-10-14T15:07:12.000Z") == "2026-10-14"


def test_utc_midnight_is_a_plain_date():
    assert local_date("2026-10-15T00:00:00.000Z") == "2026-10-15"
    assert bill_row(BILL_OCT, "acc-card")["due_date"] == "2026-10-15"


def test_bill_payment_legs_land_on_same_local_day():
    assert row(BANK_BILL_PAYMENT, "BANK")["date"] == row(CARD_BILL_PAYMENT_CREDIT, "CREDIT")["date"] == "2026-10-21"


# --- payment method & counterparty --------------------------------------------------------

def test_payment_methods():
    assert payment_method(BANK_PIX_OUT, "BANK") == "pix"
    assert payment_method(BANK_DEBIT_CARD, "BANK") == "debit"
    assert payment_method(BANK_BILL_PAYMENT, "BANK") == "other"
    assert payment_method(CARD_PURCHASE, "CREDIT") == "card"
    assert payment_method(CARD_BILL_PAYMENT_CREDIT, "CREDIT") == "other"
    # Inter card: bill payments carry op PAGAMENTO, same as purchases
    assert payment_method({"description": "PAGAMENTO ON LINE", "operationType": "PAGAMENTO"}, "CREDIT") == "other"
    assert payment_method({"description": "PAGTO DEBITO AUTOMATICO", "operationType": "PAGAMENTO"}, "CREDIT") == "other"
    assert payment_method({"description": "PAG*LOJA CENTRO", "operationType": "PAGAMENTO"}, "CREDIT") == "card"
    assert payment_method({"operationType": "TARIFA_SERVICOS_AVULSOS", "amount": -12.5}, "BANK") == "fee"
    # BTG mislabels incoming transfers as "TAXA DE CARTEIRA ADM" (TARIFA op, positive amount)
    assert payment_method({"operationType": "TARIFA_SERVICOS_AVULSOS", "amount": 3999.99}, "BANK") == "other"
    assert payment_method({"operationType": "CONVENIO_ARRECADACAO"}, "BANK") == "boleto"
    assert payment_method({"description": "Débito automático DA VIVO", "operationType": "OUTROS"}, "BANK") == "debit"
    assert payment_method({"paymentData": {"paymentMethod": "TEF"}}, "BANK") == "ted_doc"


def test_counterparty_is_receiver_for_outflows_and_payer_for_inflows():
    out = row(BANK_PIX_OUT, "BANK")
    assert (out["counterparty_name"], out["counterparty_doc"]) == ("LOJA EXEMPLO LTDA", "00111222000103")
    inn = row(BANK_PIX_IN, "BANK")
    assert (inn["counterparty_name"], inn["counterparty_doc"]) == ("EMPRESA CLIENTE LTDA", "99888777000165")


def test_card_counterparty_comes_from_merchant():
    r = row(CARD_PURCHASE, "CREDIT")
    assert (r["counterparty_name"], r["counterparty_doc"]) == ("ONG EXEMPLO", "12345678000190")


# --- installments / bill month ---------------------------------------------------------------

def test_posted_installment_is_billed_in_its_bill_month_not_purchase_date():
    r = row(CARD_INSTALLMENT_POSTED, "CREDIT")
    assert r["date"] == "2026-06-11" and r["purchase_date"] == "2026-06-11"
    assert (r["installment_number"], r["installment_total"]) == (2, 10)
    assert r["bill_due_date"] == "2026-08-17" and r["bill_month"] == "2026-08"


def test_future_installment_uses_forecast_month():
    r = row(CARD_INSTALLMENT_FUTURE, "CREDIT")
    assert r["status"] == "PENDING" and r["bill_id"] is None
    assert r["bill_month"] == "2027-04"


def test_bank_rows_have_no_bill_month():
    assert row(BANK_PIX_OUT, "BANK")["bill_month"] is None


# --- accounts ---------------------------------------------------------------------------------

def test_account_row_masks_number_and_sets_default_role():
    r = account_row(CHECKING_ACCOUNT)
    assert r["number_masked"] == "******7890" and r["role"] == "checking"
    assert r["owner_doc"] == MY_CPF
    assert account_row(CARD_ACCOUNT)["role"] == "credit_card"
