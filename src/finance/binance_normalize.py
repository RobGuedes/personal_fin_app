"""Pure Binance raw record -> `transactions` row functions (no I/O)."""

from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

from finance.normalize import dumps

ACCOUNT_ID = "binance"
LOCAL_TZ = timezone(timedelta(hours=-3))  # America/Sao_Paulo, no DST since 2019

Rate = Callable[[str, str], "float | None"]


def account_row(balance_brl: "float | None") -> dict:
    return {
        "id": ACCOUNT_ID, "item_id": ACCOUNT_ID, "type": "BANK", "subtype": "BINANCE",
        "name": "Binance", "institution": "Binance", "number_masked": None,
        "owner_doc": None, "currency": "USDT", "balance": balance_brl,
        "role": "investment", "raw_json": "{}",
    }


def item_row(now: str) -> dict:
    return {"id": ACCOUNT_ID, "connector_name": "Binance", "status": "UPDATED",
            "last_updated_at": now, "raw_json": "{}"}


def local_day(value: "int | str") -> str:
    if isinstance(value, str):
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    else:
        dt = datetime.fromtimestamp(value / 1000, tz=UTC)
    return dt.astimezone(LOCAL_TZ).date().isoformat()


def mask_address(address: str) -> str:
    return "…" + address[-4:]


def _row(*, id: str, date: str, description: str, amount: float, norm: float,
         currency: str, raw: str, counterparty: "str | None" = None) -> dict:
    return {
        "id": id, "account_id": ACCOUNT_ID, "date": date, "description": description,
        "description_raw": None, "amount": amount, "amount_normalized": norm,
        "currency": currency, "type": "CREDIT" if amount > 0 else "DEBIT",
        "status": "POSTED", "operation_type": None, "pluggy_category": None,
        "pluggy_category_id": None, "counterparty_name": counterparty,
        "counterparty_doc": None, "payment_method": "other", "installment_number": None,
        "installment_total": None, "purchase_date": None, "bill_id": None,
        "bill_due_date": None, "bill_month": None, "raw_json": raw,
    }


NORM_DP = 6  # Binance BRL values are stored to 6 dp so "unpriced" (== 0) is exact


def is_unpriced(row_or_values: "dict | tuple") -> bool:
    """A non-zero coin amount whose BRL value is 0: no price was available.
    Accepts a row dict or an (amount, amount_normalized) pair."""
    if isinstance(row_or_values, dict):
        amount, norm = row_or_values["amount"], row_or_values["amount_normalized"]
    else:
        amount, norm = row_or_values
    return amount != 0 and norm == 0


def _brl(amount: float, asset: str, day: str, rate: Rate, missing: "Counter | None" = None) -> float:
    r = rate(asset, day)
    if r is None:
        if missing is not None:
            missing[asset] += 1
        return 0.0
    return round(amount * r, NORM_DP)


def deposit_row(rec: dict, rate: Rate, missing: "Counter | None" = None) -> "dict | None":
    if rec.get("status") != 1:
        return None
    amount = float(rec["amount"])
    day = local_day(rec["insertTime"])
    return _row(
        id=f"binance:dep:{rec['id']}", date=day,
        description=f"Binance deposit {rec['coin']} ({rec['network']})",
        amount=amount, norm=_brl(amount, rec["coin"], day, rate, missing),
        currency=rec["coin"], raw=dumps(rec),
    )


def withdrawal_row(rec: dict, rate: Rate, missing: "Counter | None" = None) -> "dict | None":
    if rec.get("status") != 6:
        return None
    amount = -round(float(rec["amount"]) + float(rec.get("transactionFee") or 0), 8)
    day = local_day(rec["applyTime"])
    masked = mask_address(rec["address"])
    return _row(
        id=f"binance:wd:{rec['id']}", date=day,
        description=f"Binance withdrawal {rec['coin']} ({rec['network']}) → {masked}",
        amount=amount, norm=_brl(amount, rec["coin"], day, rate, missing),
        currency=rec["coin"], raw=dumps(rec), counterparty=masked,
    )


def fiat_row(rec: dict, transaction_type: int) -> "dict | None":
    if rec.get("status") != "Successful":
        return None
    sign = 1 if transaction_type == 0 else -1
    amount = sign * float(rec["amount"])
    label = "deposit" if transaction_type == 0 else "withdrawal"
    return _row(
        id=f"binance:fiat:{rec['orderNo']}", date=local_day(rec["createTime"]),
        description=f"Binance BRL {label}", amount=amount, norm=round(amount, 2),
        currency="BRL", raw=dumps(rec),
    )


def earn_rows(rewards: list[dict], distributions: list[dict], rate: Rate,
              missing: "Counter | None" = None) -> list[dict]:
    """Monthly roll-ups. BRL value = sum over priced items; unpriced items add 0 (counted in `missing`)."""
    groups: dict[tuple[str, str], list[tuple[int, str, float, dict]]] = defaultdict(list)
    for rec in rewards:
        ts = rec["time"]
        groups[(local_day(ts)[:7], rec["asset"])].append((ts, local_day(ts), float(rec["rewards"]), rec))
    for rec in distributions:
        ts = rec["divTime"]
        groups[(local_day(ts)[:7], rec["asset"])].append((ts, local_day(ts), float(rec["amount"]), rec))

    rows = []
    for (month, asset), items in sorted(groups.items()):
        items.sort(key=lambda i: i[0])
        amount = round(sum(i[2] for i in items), 8)
        rates = [rate(asset, i[1]) for i in items]
        if missing is not None:
            missing[asset] += sum(1 for r in rates if r is None)
        norm = round(sum(i[2] * r for i, r in zip(items, rates, strict=True) if r is not None), NORM_DP)
        rows.append(_row(
            id=f"binance:earn:{month}:{asset}", date=items[-1][1],
            description=f"Binance Earn interest {asset} {month}",
            amount=amount, norm=norm, currency=asset,
            raw=dumps([i[3] for i in items]),
        ))
    return rows
