"""Turn raw Pluggy records into table rows. Pure functions; no I/O.

Conventions (see CLAUDE.md "Pluggy findings"):
- amount_normalized: inflow to me > 0, outflow < 0. BANK amounts already follow this;
  CREDIT (card) amounts are inverted (purchases > 0), so they are negated.
- dates: Pluggy sends UTC timestamps; the calendar day is taken in America/Sao_Paulo.
"""

import json
import re
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

ROLE_BY_SUBTYPE = {
    "CHECKING_ACCOUNT": "checking",
    "SAVINGS_ACCOUNT": "savings",
    "CREDIT_CARD": "credit_card",
}

# Card-side bill payment credits. Inter files them with op PAGAMENTO like any purchase:
# "PAGAMENTO ON LINE" (paid from the Inter account) and "PAGTO DEBITO AUTOMATICO".
CARD_PAYMENT_PATTERN = re.compile(r"^(pagamento (com saldo|recebido|on line)|pagto d[ée]bito autom[áa]tico)", re.I)
AUTO_DEBIT_PATTERN = re.compile(r"d[ée]bito autom[áa]tico", re.I)


def local_date(ts: str | None) -> str | None:
    """'2026-10-30T02:59:59.000Z' -> '2026-10-29'.

    Exact UTC midnight is how Pluggy encodes date-only values (bill due/closing dates),
    so those keep their calendar day instead of shifting to the previous local day.
    """
    if not ts:
        return None
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None or (dt.utcoffset() == timedelta(0) and dt.time() == time(0)):
        return dt.date().isoformat()
    return dt.astimezone(LOCAL_TZ).date().isoformat()


def digits(value: Any) -> str | None:
    s = re.sub(r"\D", "", str(value or ""))
    return s or None


def mask_number(value: Any, keep: int = 4) -> str | None:
    s = re.sub(r"[^0-9A-Za-z]", "", str(value or ""))
    if not s:
        return None
    return "*" * max(len(s) - keep, 0) + s[-keep:]


def normalize_amount(amount: float, account_type: str) -> float:
    return -amount if account_type == "CREDIT" else amount


def payment_method(tx: dict, account_type: str) -> str:
    pm = ((tx.get("paymentData") or {}).get("paymentMethod") or "").upper()
    op = (tx.get("operationType") or "").upper()
    desc = tx.get("description") or ""
    if account_type == "CREDIT":
        if op == "PAGAMENTO_FATURA" or CARD_PAYMENT_PATTERN.match(desc):
            return "other"
        return "card"
    if pm == "PIX" or op == "PIX":
        return "pix"
    if pm in ("TED", "TEF", "DOC") or op in ("TED", "DOC", "TRANSFERENCIA_MESMA_INSTITUICAO"):
        return "ted_doc"
    if pm == "BOLETO" or op in ("BOLETO", "CONVENIO_ARRECADACAO"):
        return "boleto"
    # BTG labels some incoming transfers "TAXA DE CARTEIRA ADM" with a TARIFA op; a fee only takes money out.
    if op.startswith("TARIFA") and tx.get("amount", 0) < 0:
        return "fee"
    if op == "CARTAO" or AUTO_DEBIT_PATTERN.search(desc):
        return "debit"
    return "other"


def counterparty(tx: dict, amount_normalized: float) -> tuple[str | None, str | None]:
    """The other side of the movement: receiver for outflows, payer for inflows, else merchant."""
    pd = tx.get("paymentData") or {}
    side = pd.get("receiver") if amount_normalized < 0 else pd.get("payer")
    side = side or {}
    merchant = tx.get("merchant") or {}
    name = side.get("name") or merchant.get("businessName") or merchant.get("name")
    doc = digits((side.get("documentNumber") or {}).get("value")) or digits(merchant.get("cnpj"))
    return name, doc


def account_row(acc: dict) -> dict:
    return {
        "id": acc["id"],
        "item_id": acc["itemId"],
        "type": acc.get("type"),
        "subtype": acc.get("subtype"),
        "name": acc.get("name"),
        # No institution field on MeuPluggy accounts; the bank is in the account name.
        "institution": acc.get("marketingName") or acc.get("name"),
        "number_masked": mask_number(acc.get("number")),
        "owner_doc": digits(acc.get("taxNumber")),
        "currency": acc.get("currencyCode"),
        "balance": acc.get("balance"),
        "role": ROLE_BY_SUBTYPE.get(acc.get("subtype") or "", "other"),
        "raw_json": dumps(acc),
    }


def bill_row(bill: dict, account_id: str) -> dict:
    return {
        "id": bill["id"],
        "account_id": account_id,
        "due_date": local_date(bill.get("dueDate")),
        "closing_date": local_date(bill.get("billClosingDate")),
        "total_amount": bill.get("totalAmount"),
        "minimum_payment": bill.get("minimumPaymentAmount"),
        "currency": bill.get("totalAmountCurrencyCode"),
        "raw_json": dumps(bill),
    }


def transaction_row(tx: dict, account_type: str, bill_due_dates: dict[str, str]) -> dict:
    """`bill_due_dates` maps bill id -> local due date, to place card charges in their bill month."""
    amount_norm = normalize_amount(tx["amount"], account_type)
    name, doc = counterparty(tx, amount_norm)
    cc = tx.get("creditCardMetadata") or {}
    bill_id = cc.get("billId")
    bill_due = bill_due_dates.get(bill_id) if bill_id else None
    bill_month = bill_due[:7] if bill_due else cc.get("billForecastDate")
    return {
        "id": tx["id"],
        "account_id": tx["accountId"],
        "date": local_date(tx["date"]),
        "description": tx.get("description"),
        "description_raw": tx.get("descriptionRaw"),
        "amount": tx["amount"],
        "amount_normalized": amount_norm,
        "currency": tx.get("currencyCode"),
        "type": tx.get("type"),
        "status": tx.get("status"),
        "operation_type": tx.get("operationType"),
        "pluggy_category": tx.get("category"),
        "pluggy_category_id": tx.get("categoryId"),
        "counterparty_name": name,
        "counterparty_doc": doc,
        "payment_method": payment_method(tx, account_type),
        "installment_number": cc.get("installmentNumber"),
        "installment_total": cc.get("totalInstallments"),
        "purchase_date": local_date(cc.get("purchaseDate")),
        "bill_id": bill_id,
        "bill_due_date": bill_due,
        "bill_month": bill_month if account_type == "CREDIT" else None,
        "raw_json": dumps(tx),
    }


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
