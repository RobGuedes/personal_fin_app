"""Anonymized transaction samples copied from real Pluggy (MeuPluggy) shapes.

Names, CPF/CNPJ, account numbers and amounts are invented; signs, timestamp shapes and field layout follow the API.
"""

from pathlib import Path

MY_CPF = "11122233344"

BANK_PIX_OUT = {
    "id": "tx-pix-out", "accountId": "acc-checking", "date": "2026-10-30T02:59:59.000Z",
    "description": "Pagamento de Pix QR Code LOJA EXEMPLO", "descriptionRaw": "Pagamento de Pix QR Code LOJA EXEMPLO",
    "amount": -1765.43, "currencyCode": "BRL", "type": "DEBIT", "status": "POSTED", "operationType": "PIX",
    "category": "Shopping", "categoryId": "08000000",
    "paymentData": {
        "paymentMethod": "PIX",
        "payer": {"documentNumber": {"type": "CPF", "value": MY_CPF}, "name": None},
        "receiver": {"documentNumber": {"type": "CNPJ", "value": "00111222000103"},
                     "name": "LOJA EXEMPLO LTDA", "routingNumber": "383", "routingNumberISPB": "21018182"},
    },
}

BANK_PIX_IN = {
    "id": "tx-pix-in", "accountId": "acc-checking", "date": "2026-10-28T03:00:00.000Z",
    "description": "Pix recebido EMPRESA CLIENTE LTDA", "descriptionRaw": "Pix recebido EMPRESA CLIENTE LTDA",
    "amount": 512.34, "currencyCode": "BRL", "type": "CREDIT", "status": "POSTED", "operationType": "PIX",
    "category": "Transfer - PIX", "categoryId": "05070000",
    "paymentData": {
        "paymentMethod": "PIX",
        "payer": {"documentNumber": {"type": "CNPJ", "value": "99888777000165"}, "name": "EMPRESA CLIENTE LTDA"},
        "receiver": {"documentNumber": {"type": "CPF", "value": MY_CPF}, "name": None},
    },
}

BANK_DEBIT_CARD = {
    "id": "tx-debit-card", "accountId": "acc-checking", "date": "2026-10-30T02:59:59.000Z",
    "description": "Compra débito Padaria Exemplo", "descriptionRaw": "Compra débito Padaria Exemplo",
    "amount": -18.45, "currencyCode": "BRL", "type": "DEBIT", "status": "POSTED", "operationType": "CARTAO",
    "category": "Shopping", "categoryId": "08000000", "paymentData": {"paymentMethod": "OTHER"},
}

BANK_BILL_PAYMENT = {
    "id": "tx-bill-pay", "accountId": "acc-checking", "date": "2026-10-22T02:59:59.000Z",
    "description": "Pagamento de fatura Fatura Paga Cartao Exemplo",
    "descriptionRaw": "Pagamento de fatura Fatura Paga Cartao Exemplo",
    "amount": -3210.0, "currencyCode": "BRL", "type": "DEBIT", "status": "POSTED", "operationType": "OUTROS",
    "category": "Credit card payment", "categoryId": "05100000", "paymentData": {"paymentMethod": "OTHER"},
}

CARD_PURCHASE = {
    "id": "tx-card-buy", "accountId": "acc-card", "date": "2026-10-14T15:07:12.000Z",
    "description": "ONG EXEMPLO CIDADEBR", "descriptionRaw": "ONG EXEMPLO CIDADEBR",
    "amount": 2950.4, "currencyCode": "BRL", "type": "DEBIT", "status": "POSTED", "operationType": "PAGAMENTO",
    "category": "Donations", "categoryId": "16000000",
    "merchant": {"businessName": "ONG EXEMPLO", "cnpj": "12.345.678/0001-90"},
    "creditCardMetadata": {"cardNumber": "0000", "billId": "bill-oct", "payeeMCC": 8398,
                           "transactionDateTime": "2026-10-14T15:07:12.000Z"},
}

CARD_BILL_PAYMENT_CREDIT = {
    "id": "tx-card-pay", "accountId": "acc-card", "date": "2026-10-21T03:00:00.000Z",
    "description": "PAGAMENTO COM SALDO", "descriptionRaw": "PAGAMENTO COM SALDO",
    "amount": -3210.0, "currencyCode": "BRL", "type": "CREDIT", "status": "POSTED", "operationType": "OUTROS",
    "category": "Transfers", "categoryId": "05000000", "creditCardMetadata": {"billId": "bill-oct"},
}

CARD_INSTALLMENT_POSTED = {
    "id": "tx-inst-2", "accountId": "acc-card", "date": "2026-06-11T15:04:18.000Z",
    "description": "LOJA ELETRO 02/10", "descriptionRaw": "LOJA ELETRO 02/10",
    "amount": 1111.22, "currencyCode": "BRL", "type": "DEBIT", "status": "POSTED", "operationType": "PAGAMENTO",
    "category": "Electronics", "categoryId": "08010000",
    "creditCardMetadata": {"installmentNumber": 2, "totalInstallments": 10, "billId": "bill-aug",
                           "purchaseDate": "2026-06-11T15:04:18.000Z", "billForecastDate": "2026-08",
                           "paymentType": "INSTALLMENT"},
}

CARD_INSTALLMENT_FUTURE = {
    "id": "tx-inst-10", "accountId": "acc-card", "date": "2027-04-05T03:00:00.000Z",
    "description": "LOJA ELETRO 10/10", "descriptionRaw": "LOJA ELETRO 10/10",
    "amount": 1111.22, "currencyCode": "BRL", "type": "DEBIT", "status": "PENDING", "operationType": "PAGAMENTO",
    "category": "Electronics", "categoryId": "08010000",
    "creditCardMetadata": {"installmentNumber": 10, "totalInstallments": 10,
                           "purchaseDate": "2026-06-11T15:04:18.000Z", "billForecastDate": "2027-04",
                           "paymentType": "INSTALLMENT"},
}

BILL_AUG = {"id": "bill-aug", "dueDate": "2026-08-17T00:00:00.000Z", "billClosingDate": "2026-08-08T00:00:00.000Z",
            "totalAmount": 5678.90, "totalAmountCurrencyCode": "BRL", "minimumPaymentAmount": 876.54, "payments": []}
BILL_OCT = {"id": "bill-oct", "dueDate": "2026-10-15T00:00:00.000Z", "billClosingDate": "2026-10-08T00:00:00.000Z",
            "totalAmount": 5432.10, "totalAmountCurrencyCode": "BRL", "minimumPaymentAmount": 912.34, "payments": []}

CHECKING_ACCOUNT = {"id": "acc-checking", "itemId": "item-1", "type": "BANK", "subtype": "CHECKING_ACCOUNT",
                    "name": "itau", "number": "1234/56789-0", "taxNumber": "111.222.333-44",
                    "currencyCode": "BRL", "balance": 1000.0}
CARD_ACCOUNT = {"id": "acc-card", "itemId": "item-1", "type": "CREDIT", "subtype": "CREDIT_CARD",
                "name": "CARTAO EXEMPLO VISA", "number": "0000", "currencyCode": "BRL", "balance": 1111.22}

# Tests use these copies (settings + Binance rules, category tree with non-zero settings), never the
# user-edited config/rules.yaml / config/categories.yaml.
RULES_FIXTURE = Path(__file__).parent / "fixtures" / "rules.yaml"
CATEGORIES_FIXTURE = Path(__file__).parent / "fixtures" / "categories.yaml"
