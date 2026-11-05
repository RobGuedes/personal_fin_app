"""Search box syntax: free text plus an optional amount comparison ("> 1.600,00", "=1600", "< 99,9")."""

import re
from dataclasses import dataclass
from typing import Literal

from finance.transfers import fold

_AMOUNT = re.compile(r"(?:^|\s)([<>=]?)\s*(\d[\d.,]*)\s*$")


@dataclass
class Query:
    text: str
    op: Literal[">", "<", "="] | None = None
    amount: float | None = None


def parse_amount(raw: str) -> float | None:
    s = raw.strip()
    if "," in s:  # Brazilian: dots group thousands, comma is the decimal separator
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", s):  # "1.600" / "1.600.000" = thousands
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_query(q: str) -> Query:
    """An amount is recognised only with an explicit operator (so "7 eleven" stays text)."""
    m = _AMOUNT.search(q or "")
    if m and m.group(1):
        amount = parse_amount(m.group(2))
        if amount is not None:
            return Query(text=fold(q[:m.start()]), op=m.group(1), amount=amount)  # type: ignore[arg-type]
    return Query(text=fold(q))
