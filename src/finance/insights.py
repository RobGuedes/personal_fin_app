"""Usual spend, unusual-spend notes and the renda split. Pure functions over ledger rows."""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from statistics import median
from typing import Any, Literal

from .aggregate import PNL_OUTFLOW_LINES, breakdown, line_totals
from .classify import GENERIC_PREFIXES, UNCATEGORIZED

MIN_MONTHS = 3


def day_of(row: dict) -> int:
    """Day of month; installments billed into a later month count from day 1."""
    return int(row["date"][8:10]) if row["date"][:7] == row["month"] else 1


def _days_in(month: str) -> int:
    return calendar.monthrange(int(month[:4]), int(month[5:7]))[1]


def _prev_months(month: str, n: int) -> list[str]:
    y, m = int(month[:4]), int(month[5:7])
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y}-{m:02d}")
    return out[::-1]


def _usual(rows, category, month, history, day=None) -> float | None:
    months = _prev_months(month, history)
    active = {r["month"] for r in rows if r["month"] in months}
    if len(active) < MIN_MONTHS:
        return None
    totals = dict.fromkeys(months, 0.0)
    for r in rows:
        if r["category_id"] != category or r["month"] not in totals:
            continue
        if day is None or day_of(r) <= min(day, _days_in(r["month"])):
            totals[r["month"]] += -r["amount"]
    return float(median(totals.values()))


def usual_to_date(rows, category: str, month: str, day: int, history: int = 6) -> float | None:
    return _usual(rows, category, month, history, day)


def usual_for_month(rows, category: str, month: str, history: int = 6) -> float | None:
    return _usual(rows, category, month, history)


def is_unusual(spent: float, reference_to_date: float) -> bool:
    return spent > 1.25 * reference_to_date and spent - reference_to_date >= 300


def unusual_note(rows, category: str, month: str, excess: float, notes: dict[str, str],
                 day: int | None = None) -> str | None:
    """The single transaction explaining at least half of `excess`, described for humans."""
    seen: dict[str, dict] = {}
    for r in rows:
        if r["category_id"] == category and r["month"] == month and r["amount"] < 0 \
                and (day is None or day_of(r) <= day):
            seen.setdefault(r["id"], r)
    best = None
    for r in seen.values():
        amount = -r["amount"]
        if amount >= 0.5 * excess and (best is None or amount > best[0]):
            best = (amount, r)
    if best is None:
        return None
    r = best[1]
    if notes.get(r["id"]):
        return notes[r["id"]]
    text = GENERIC_PREFIXES.sub("", r.get("description") or "").strip()
    return text or None


@dataclass
class CategoryStatus:
    category_id: str
    spent: float
    reference_to_date: float | None
    reference_month: float | None
    reference_kind: Literal["usual", "budget", "none"]
    unusual: bool
    pct_over: float | None
    note: str | None


def compare(rows, month: str, day: int, budgets: dict[str, float], notes: dict[str, str] | None = None,
            history: int = 6) -> list[CategoryStatus]:
    notes = notes or {}
    cats = {r["category_id"] for r in rows if r["line"] in PNL_OUTFLOW_LINES}
    spent = {c: 0.0 for c in cats}
    for r in rows:
        if r["line"] in PNL_OUTFLOW_LINES and r["month"] == month and day_of(r) <= day:
            spent[r["category_id"]] += -r["amount"]
    out = []
    for c in cats | set(budgets):
        s = round(spent.get(c, 0.0), 2)
        kind: Literal["usual", "budget", "none"]
        ref_d: float | None
        ref_m: float | None
        if c in budgets:
            kind, ref_m = "budget", float(budgets[c])
            ref_d = ref_m * min(day, _days_in(month)) / _days_in(month)
        else:
            ref_d = usual_to_date(rows, c, month, day, history)
            ref_m = usual_for_month(rows, c, month, history)
            kind = "usual" if ref_d is not None else "none"
        if s == 0 and kind == "none":
            continue
        unusual = ref_d is not None and is_unusual(s, ref_d)
        pct = (s / ref_d - 1) if ref_d else None
        note = unusual_note(rows, c, month, s - ref_d, notes, day) if unusual and ref_d is not None else None
        out.append(CategoryStatus(c, s, ref_d, ref_m, kind, unusual, pct, note))
    return sorted(out, key=lambda x: (-x.spent, x.category_id))


@dataclass
class RendaSplit:
    renda: float
    despesas: float
    outros: float
    sobrou: float
    scale: float
    deficit: bool


def renda_split(totals: dict[str, float]) -> RendaSplit:
    renda = totals.get("income", 0.0)
    despesas = -totals.get("expenses", 0.0)
    outros = -(totals.get("tax_provision", 0.0) + totals.get("commissions", 0.0))
    sobrou = totals.get("net_income", 0.0)
    return RendaSplit(renda, despesas, outros, sobrou, max(renda, despesas + outros), sobrou < 0)


# --- periods and Sankey (web app, Milestone B) -----------------------------------------------------

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def shift_month(month: str, delta: int) -> str:
    n = int(month[:4]) * 12 + int(month[5:7]) - 1 + delta
    return f"{n // 12}-{n % 12 + 1:02d}"


def period_months(period: str, current: str, all_months: list[str]) -> list[str]:
    """Months of a period string, ascending: `month:YYYY-MM`, `last12`, `year:YYYY`.

    - `last12`: the 12 calendar months ending at `current` inclusive (ruling R1), zero-filled.
    - `year:YYYY`: January..December of that year, capped at `current`; a year before the first data month
      still returns its 12 months (all zero) so the UI shows an empty table, not an error.
    - Months with no rows are always present: callers zero-fill. `all_months` (months that have data) is accepted
      for the interface but does not shorten any period.
    - Raises ValueError for a malformed period or a month/year after `current`.
    """
    if period == "last12":
        return [shift_month(current, -i) for i in range(11, -1, -1)]
    kind, _, value = period.partition(":")
    if kind == "month" and _MONTH_RE.fullmatch(value):
        if value > current:
            raise ValueError(f"month after current: {period}")
        return [value]
    if kind == "year" and re.fullmatch(r"\d{4}", value):
        if value > current[:4]:
            raise ValueError(f"year after current: {period}")
        months = [f"{value}-{m:02d}" for m in range(1, 13)]
        return [m for m in months if m <= current]
    raise ValueError(f"bad period: {period!r}")


# pt-BR labels of the P&L lines (the taxonomy's own are English).
LINE_LABELS_PT = {
    "income": "1. Renda", "tax_provision": "2. Provisão de impostos", "commissions": "3. Comissões pagas",
    "expenses": "4. Despesas", "net_income": "5. Sobrou",
    "investments": "6. Investimentos (− = aportes)", "excluded": "(fora do resultado)",
}
_SANKEY_LINE_LABELS = {"commissions": "Comissões pagas", "tax_provision": "Provisão de impostos"}


def _cents(v: float) -> int:
    return round(v * 100)


def _reconcile(items: list[list], target: int, rest_key: str) -> list[list]:
    """Make the cents of [key, label, cents] items add up to `target`: the surplus (wrong-sign components that
    `breakdown` dropped) is taken from the "rest" band first, then from the largest remaining bands; a deficit goes
    to the rest band (created when missing). Bands that reach zero disappear."""
    items = [list(i) for i in items]
    diff = sum(i[2] for i in items) - target
    order = sorted(items, key=lambda i: (i[0] != rest_key, -i[2]))
    for it in order:
        if diff <= 0:
            break
        cut = min(it[2], diff)
        it[2] -= cut
        diff -= cut
    if diff < 0:
        rest = next((i for i in items if i[0] == rest_key), None)
        if rest is None:
            return items + [[rest_key, "Outras", -diff]]
        rest[2] -= diff
    return [i for i in items if i[2] > 0]


def _filter(key: str, kind: str) -> dict | None:
    """Transaction filter (GET /transactions params) behind a node, or None when it has no transactions."""
    if kind == "line":
        return None if key == "tax_provision" else {"line": key}  # the 6% provision is not a bank event
    if key in ("outras_rendas", "outras_despesas"):
        return {"line": "income" if key == "outras_rendas" else "expenses"}
    if key.startswith("uncategorized:"):
        return {"category": UNCATEGORIZED, "line": key.split(":", 1)[1]}
    if key.startswith("manual:") or key in ("reservas_usadas", "sobrou", "renda"):
        return None
    return {"category": key}


def sankey(table: list[dict], months: list[str], keep_sources: int = 5, keep_expenses: int = 6) -> dict:
    """Spec section 7 diagram from a (pt-BR labelled) `aggregate.pnl` table over `months`.

    Everything is computed in integer cents so the invariant holds exactly:
    sum(sources) == middle == sum(targets). Sobrou / Reservas usadas come from line 5 (income minus lines 2-4):
    Sobrou = line 5 when > 0, Reservas usadas = -line 5 when < 0.

    Left: line-1 components (top `keep_sources` + "Outras rendas") adding up to line 1, plus "Reservas usadas" in a
    deficit. Middle "Renda" = what flows out on the right (= line 1 when line 5 >= 0; line 1 + reservas in a deficit);
    its `income` field is line 1 itself. Right: "Sobrou", then line 3, 2 (outflows as positive bands), then
    line-4 components (top `keep_expenses` + "Outras despesas"), adding up to the real outflows. Components of the
    wrong sign (a refund making an expense category net positive; a net-positive line) are dropped by `breakdown` and
    clamped, which would overstate a side: the surplus is netted into "Outras rendas"/"Outras despesas" and, if that is
    not enough, taken from the largest bands of that side (`_reconcile`). Zero nodes are skipped; line 6 is not here.

    Node `key`: category id (or `uncategorized:<line>` / `manual:<line>`) for components; line key (`commissions`,
    `tax_provision`) for line nodes; fixed `renda`, `outras_rendas`, `outras_despesas`,
    `reservas_usadas`, `sobrou`. Node `id` = `src:`/`mid`/`dst:` + key. Node `filter` = the GET /transactions params
    ({category?, line?}) to list its transactions, None when it has none (sobrou, renda, reservas, manual, provision).
    """
    totals = line_totals(table, months)
    income_c = _cents(totals.get("income", 0.0))
    signed = {k: _cents(totals.get(k, 0.0)) for k in ("tax_provision", "commissions", "expenses")}
    out_c = -sum(signed.values())  # real outflows of lines 2-4
    lines_c = {k: max(0, -signed[k]) for k in ("commissions", "tax_provision")}
    exp_c = max(0, -signed["expenses"])

    def top(line: str, keep: int, rest_total: int, rest_key: str, rest_label: str):
        items: list[list[Any]] = [[k, label, _cents(v)] for k, label, v in breakdown(table, line, months)][:keep]
        rest = rest_total - sum(i[2] for i in items)
        if rest > 0:
            items.append([rest_key, rest_label, rest])
        return items

    s_target, o_target = max(0, income_c), max(0, out_c)
    sources = _reconcile(top("income", keep_sources, income_c, "outras_rendas", "Outras rendas"), s_target,
                         "outras_rendas")
    spending = top("expenses", keep_expenses, exp_c, "outras_despesas", "Outras despesas")
    right = [[k, _SANKEY_LINE_LABELS[k], lines_c[k], "line"] for k in ("commissions", "tax_provision")]
    right = [i for i in right if i[2]]
    pool = _reconcile([[k, label, c] for k, label, c, _ in right] + spending, o_target, "outras_despesas")
    line_keys = {i[0] for i in right}
    sobrou, reservas = max(0, s_target - o_target), max(0, o_target - s_target)
    sources = [i for i in sources if i[2] > 0]
    if reservas:
        sources.append(["reservas_usadas", "Reservas usadas", reservas])
    order = {"commissions": 0, "tax_provision": 1}
    lines_part = sorted((i for i in pool if i[0] in line_keys), key=lambda i: order[i[0]])
    targets = (([["sobrou", "Sobrou", sobrou]] if sobrou else []) + lines_part
               + [i for i in pool if i[0] not in line_keys])
    middle = sum(i[2] for i in sources)
    if middle != sum(i[2] for i in targets):  # explicit, not `assert`: must also hold under python -O
        raise ValueError("sankey: left and right totals differ")
    if not middle:
        return {"nodes": [], "links": []}
    nodes = [{"id": f"src:{k}", "label": label, "side": "source", "key": k, "value": c / 100,
              "filter": _filter(k, "node")} for k, label, c in sources]
    nodes.append({"id": "mid", "label": "Renda", "side": "middle", "key": "renda", "value": middle / 100,
                  "filter": None, "income": income_c / 100})
    nodes += [{"id": f"dst:{k}", "label": label, "side": "target", "key": k, "value": c / 100,
               "filter": _filter(k, "line" if k in line_keys else "node")} for k, label, c in targets]
    links = [{"source": n["id"], "target": "mid", "value": n["value"]} for n in nodes if n["side"] == "source"]
    links += [{"source": "mid", "target": n["id"], "value": n["value"]} for n in nodes if n["side"] == "target"]
    return {"nodes": nodes, "links": links}
