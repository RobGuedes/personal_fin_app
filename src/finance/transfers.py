"""Detect money that only moves between my own pockets, so it is never counted as income/expense.

Passes over transactions that have no manual classification, in this order:
1. card_bill_payment: card-side payment credit <-> bank debit of the same amount, within N days.
   Unmatched card-side credits are still tagged, with low confidence (review queue).
2. own_transfer: bank outflow <-> bank inflow of the same amount on two different accounts, within
   N days, where at least one leg points at me (my CPF, my name, or Pluggy's "Same person transfer").
3. investment_contribution / investment_redemption: one-legged by nature (the other side is a
   fund/CDB/stock, not an account), detected from config patterns.
4. Leftover legs that point at me (the other account is not connected) -> own_transfer with low
   confidence (review queue).
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

MATCHED_CONFIDENCE = 1.0
UNMATCHED_CONFIDENCE = 0.5
AMOUNT_TOLERANCE = 0.005


@dataclass
class Detection:
    transaction_id: str
    category_id: str
    confidence: float


@dataclass
class Link:
    from_id: str
    to_id: str | None
    link_type: str


def fold(text: str | None) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def name_matcher(my_names: list[str]):
    """Match on the first three words of my name (descriptions are often truncated)."""
    prefixes = {" ".join(fold(n).split()[:3]) for n in my_names if n and n.strip()}
    prefixes.discard("")

    def matches(text: str | None) -> bool:
        t = fold(text)
        return bool(t) and any(p in t for p in prefixes)

    return matches


def _days(a: dict, b: dict) -> int:
    return abs((date.fromisoformat(a["date"]) - date.fromisoformat(b["date"])).days)


def _same_amount(a: dict, b: dict) -> bool:
    return abs(abs(a["amount_normalized"]) - abs(b["amount_normalized"])) < AMOUNT_TOLERANCE


def _pair(outs: list[dict], ins: list[dict], window: int, ok=lambda o, i: True,
          prefer=lambda o, i: False) -> list[tuple[dict, dict]]:
    """Greedy one-to-one matching of outflows to inflows: same amount, closest dates first; on equal
    distance, `prefer`red pairs win, then legs with the same payment method (Pix <-> Pix). That matters
    for chains such as bank -Pix-> XP digital account -> XP investment account, where one amount
    appears four times."""
    candidates = [
        (_days(o, i), not prefer(o, i), o["payment_method"] != i["payment_method"], o["date"], o["id"], i["id"], o, i)
        for o in outs for i in ins
        if o["account_id"] != i["account_id"] and _same_amount(o, i) and _days(o, i) <= window and ok(o, i)
    ]
    used: set[str] = set()
    pairs = []
    for *_, o, i in sorted(candidates, key=lambda c: c[:6]):
        if o["id"] in used or i["id"] in used:
            continue
        used |= {o["id"], i["id"]}
        pairs.append((o, i))
    return pairs


def detect(txs: list[dict], account_types: dict[str, str], my_cpfs: set[str], my_names: list[str],
           transfer_cfg: dict, investment_cfg: dict,
           account_items: dict[str, str] | None = None) -> tuple[list[Detection], list[Link]]:
    """`txs` are transaction rows (dicts) without a manual classification. `account_items` maps account
    id -> Pluggy item id: a card payment from the card's own bank wins over a same-amount debit elsewhere
    (e.g. a Pix to that bank on the day its bill is paid)."""
    items = account_items or {}
    detections: list[Detection] = []
    links: list[Link] = []
    taken: set[str] = set()
    is_me = name_matcher(my_names)

    def tag(tx: dict, category: str, confidence: float) -> None:
        detections.append(Detection(tx["id"], category, confidence))
        taken.add(tx["id"])

    bank = [t for t in txs if account_types.get(t["account_id"]) == "BANK"]
    card = [t for t in txs if account_types.get(t["account_id"]) == "CREDIT"]

    # 1. Card bill payments
    card_credits = [t for t in card if t["payment_method"] == "other" and t["amount_normalized"] > 0]
    bank_debits = [t for t in bank if t["amount_normalized"] < 0]
    def same_bank(d, c):
        return d["account_id"] in items and items[d["account_id"]] == items.get(c["account_id"])

    for debit, credit in _pair(bank_debits, card_credits, transfer_cfg.get("card_payment_window_days", 3),
                               prefer=same_bank):
        tag(debit, "card_bill_payment", MATCHED_CONFIDENCE)
        tag(credit, "card_bill_payment", MATCHED_CONFIDENCE)
        links.append(Link(debit["id"], credit["id"], "card_bill_payment"))
    for credit in card_credits:
        if credit["id"] not in taken:
            tag(credit, "card_bill_payment", UNMATCHED_CONFIDENCE)
            links.append(Link(credit["id"], None, "card_bill_payment"))

    # 2. Own transfers
    own_account = [re.compile(p, re.I) for p in transfer_cfg.get("own_account_patterns", [])]

    def points_at_me(t: dict) -> bool:
        return (
            (t.get("counterparty_doc") or "") in my_cpfs
            or is_me(t.get("counterparty_name"))
            or is_me(t.get("description"))
            or t.get("pluggy_category") == "Same person transfer"
            or any(p.search(t.get("description") or "") for p in own_account)
        )

    free = [t for t in bank if t["id"] not in taken]
    outs = [t for t in free if t["amount_normalized"] < 0]
    ins = [t for t in free if t["amount_normalized"] > 0]
    window = transfer_cfg.get("own_transfer_window_days", 2)
    for o, i in _pair(outs, ins, window, ok=lambda o, i: points_at_me(o) or points_at_me(i)):
        tag(o, "own_transfer", MATCHED_CONFIDENCE)
        tag(i, "own_transfer", MATCHED_CONFIDENCE)
        links.append(Link(o["id"], i["id"], "own_transfer"))

    # 3. Investment flows
    patterns = [re.compile(p, re.I) for p in investment_cfg.get("description_patterns", [])]
    excludes = [re.compile(p, re.I) for p in investment_cfg.get("exclude_patterns", [])]
    categories = set(investment_cfg.get("pluggy_categories", []))
    op_types = set(investment_cfg.get("operation_types", []))
    docs = {re.sub(r"\D", "", str(d)) for d in investment_cfg.get("counterparty_docs", [])}

    for t in bank:
        if t["id"] in taken:
            continue
        text = f"{t.get('description') or ''} {t.get('description_raw') or ''}"
        if any(p.search(text) for p in excludes):
            continue
        if (
            t.get("pluggy_category") in categories
            or t.get("operation_type") in op_types
            or any(p.search(text) for p in patterns)
            or (t.get("counterparty_doc") or "") in docs
        ):
            link_type = "investment_contribution" if t["amount_normalized"] < 0 else "investment_redemption"
            tag(t, link_type, MATCHED_CONFIDENCE)
            links.append(Link(t["id"], None, link_type))

    # 4. One-legged own transfers (the other account is not connected). Runs after the investment
    #    pass so "transfer to my investment account" counts as a contribution, not an own transfer.
    for t in bank:
        if t["id"] not in taken and points_at_me(t):
            tag(t, "own_transfer", UNMATCHED_CONFIDENCE)
            links.append(Link(t["id"], None, "own_transfer"))

    return detections, links
