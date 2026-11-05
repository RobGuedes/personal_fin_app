"""Monthly P&L / cash-flow queries over classified transactions. No UI code here.

Month assignment (competence view, SPEC §6.3): a transaction counts in the month of its date,
except card installments (installment_total > 1), which count in the month they are billed.
"""

import sqlite3
from collections import Counter, defaultdict

from finance.classify import UNCATEGORIZED, Taxonomy

# Effective month + P&L line for every transaction; uncategorized rows have no classification.
LEDGER_SQL = """
SELECT t.id, t.account_id, t.date, t.description, t.description_raw, t.amount_normalized AS amount,
       t.payment_method, t.counterparty_name, t.counterparty_doc, t.pluggy_category, t.status,
       t.installment_number, t.installment_total,
       json_extract(t.raw_json, '$.merchant.businessName') AS merchant_name,
       a.name AS account_name, a.number_masked AS account_number, a.type AS account_type,
       CASE WHEN t.installment_total > 1 AND t.bill_month IS NOT NULL THEN t.bill_month
            ELSE substr(t.date, 1, 7) END AS month,
       COALESCE(c.category_id, :uncategorized) AS category_id,
       c.source, c.rule_id, c.confidence
FROM transactions t
JOIN accounts a ON a.id = t.account_id
LEFT JOIN classifications c ON c.transaction_id = t.id
"""

PNL_OUTFLOW_LINES = ("commissions", "expenses")


def account_label(name: str | None, number: str | None) -> str:
    digits = (number or "").lstrip("*")
    return f"{name} {digits[-4:]}" if digits else (name or "?")


def account_labels(conn: sqlite3.Connection) -> dict[str, str]:
    """{account id: label}, unique, so two accounts
    labelled alike (a bank with two checking accounts under one number) stay distinguishable.
    Duplicates get their subtype, then a counter: "Banco 0004 (savings)", "Banco 0003 (checking 2)"."""
    rows = conn.execute("SELECT id, name, number_masked, subtype FROM accounts ORDER BY type, name, rowid").fetchall()
    labels = {r["id"]: account_label(r["name"], r["number_masked"]) for r in rows}
    for step in ("subtype", "counter"):
        counts = Counter(labels.values())
        seen: Counter = Counter()
        for r in rows:
            label = labels[r["id"]]
            if counts[label] < 2:
                continue
            if step == "subtype":
                kind = (r["subtype"] or "account").removesuffix("_ACCOUNT").replace("_", " ").lower()
                labels[r["id"]] = f"{label} ({kind})"
            else:
                seen[label] += 1
                labels[r["id"]] = f"{label[:-1]} {seen[label]})"
    return labels


def ledger(conn: sqlite3.Connection, taxonomy: Taxonomy) -> list[dict]:
    rows = []
    for r in conn.execute(LEDGER_SQL, {"uncategorized": UNCATEGORIZED}):
        row = dict(r)
        # Uncategorized money still counts: outflows as expenses, inflows as income, until reviewed.
        row["line"] = taxonomy.line_of(row["category_id"]) or ("expenses" if row["amount"] < 0 else "income")
        row["account"] = account_label(row["account_name"], row["account_number"])
        rows.append(row)
    return rows


def filter_rows(rows: list[dict], months: list[str] | None = None, accounts: list[str] | None = None,
                methods: list[str] | None = None) -> list[dict]:
    return [r for r in rows
            if (months is None or r["month"] in months)
            and (accounts is None or r["account_id"] in accounts)
            and (methods is None or r["payment_method"] in methods)]


def manual_entries(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM manual_entries ORDER BY month, id")]


def tax_provision(rows: list[dict], taxonomy: Taxonomy) -> dict[str, float]:
    """{month: -(rate x income in nf_issued categories)} — a provision, not a bank event."""
    rate = float(taxonomy.settings.get("tax_provision_rate") or 0)
    nf = {c for c, attrs in taxonomy.categories.items() if attrs.get("nf_issued")}
    out: dict[str, float] = defaultdict(float)
    for r in rows:
        if r["category_id"] in nf:
            out[r["month"]] -= r["amount"] * rate
    return {m: round(v, 2) for m, v in out.items()}


def pnl(rows: list[dict], entries: list[dict], taxonomy: Taxonomy, months: list[str]) -> list[dict]:
    """The spreadsheet structure: one dict per row with a value per month.

    Rows: P&L lines (level 0) and their categories / components (level 1), in display order.
    Excluded categories are not part of the P&L. `rows` must already be split and filtered.
    """
    months = sorted(months)
    in_range = [r for r in rows if r["month"] in months]
    by_cat: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in in_range:
        by_cat[r["category_id"]][r["month"]] += r["amount"]
    manual_by_line: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    manual_notes: dict[str, set[str]] = defaultdict(set)
    for e in entries:
        if e["month"] in months:
            manual_by_line[e["pnl_line"]][e["month"]] += e["amount"]
            manual_notes[e["pnl_line"]].add((e.get("note") or "").split(":")[0].strip())

    def row(key, label, level, line, values):
        vals = {m: round(values.get(m, 0.0), 2) for m in months}
        return {"key": key, "label": label, "level": level, "line": line, **vals}

    out: list[dict] = []
    line_totals: dict[str, dict[str, float]] = {}

    def add_line(line: str, components: list[dict]):
        total = {m: sum(c[m] for c in components) for m in months}
        line_totals[line] = total
        out.append(row(line, taxonomy.lines[line], 0, line, total))
        out.extend(c for c in components if any(c[m] for m in months))

    for line in ("income", "tax_provision", "commissions", "expenses", "investments"):
        components = []
        if line == "tax_provision":
            rate = float(taxonomy.settings.get("tax_provision_rate") or 0)
            components.append(row("provision", f"{rate:.0%} on NF income", 1, line, tax_provision(in_range, taxonomy)))
        for category, attrs in taxonomy.categories.items():
            if attrs["line"] == line:
                components.append(row(category, attrs.get("label", category), 1, line, by_cat.get(category, {})))
        if line in ("income", "expenses"):
            uncategorized: defaultdict[str, float] = defaultdict(float)
            for r in in_range:
                if r["category_id"] == UNCATEGORIZED and r["line"] == line:
                    uncategorized[r["month"]] += r["amount"]
            components.append(row(f"{UNCATEGORIZED}:{line}", "Uncategorized", 1, line, uncategorized))
        if manual_by_line.get(line):
            notes = manual_notes[line] - {""}
            label = f"Manual: {next(iter(notes))}" if len(notes) == 1 else "Manual entries"
            components.append(row(f"manual:{line}", label, 1, line, manual_by_line[line]))
        add_line(line, components)
        if line == "expenses":
            net = {m: sum(line_totals[l][m] for l in ("income", "tax_provision", "commissions", "expenses"))
                   for m in months}
            out.append(row("net_income", taxonomy.lines["net_income"], 0, "net_income", net))

    return out


def with_totals(table: list[dict], months: list[str]) -> list[dict]:
    for r in table:
        r["total"] = round(sum(r[m] for m in months), 2)
        r["average"] = round(r["total"] / len(months), 2) if months else 0.0
    return table


def expenses_by_category(rows: list[dict]) -> dict[str, dict[str, float]]:
    """{category: {month: outflow > 0}} for line 4 (refunds net against their category)."""
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if r["line"] == "expenses":
            out[r["category_id"]][r["month"]] -= r["amount"]
    return out


def top_counterparties(rows: list[dict], n: int = 20) -> list[tuple[str, float, int]]:
    """Largest P&L outflow destinations: (name, total outflow > 0, count)."""
    totals: dict[str, list] = defaultdict(lambda: [0.0, 0])
    for r in rows:
        if r["line"] in PNL_OUTFLOW_LINES and r["amount"] < 0:
            name = r["counterparty_name"] or r["merchant_name"] or r["description"] or "?"
            totals[name.strip().upper()][0] -= r["amount"]
            totals[name.strip().upper()][1] += 1
    ranked = sorted(totals.items(), key=lambda kv: -kv[1][0])[:n]
    return [(name, round(v[0], 2), v[1]) for name, v in ranked]


def outflows_by_channel(rows: list[dict]) -> dict[str, dict[str, float]]:
    """{payment_method: {month: outflow > 0}} for P&L outflows (lines 3-4)."""
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if r["line"] in PNL_OUTFLOW_LINES and r["amount"] < 0:
            out[r["payment_method"]][r["month"]] -= r["amount"]
    return out


def transfer_audit(conn: sqlite3.Connection) -> list[dict]:
    """Every transfer link with both legs, for the audit view."""
    sql = """
    SELECT l.link_type, c.confidence,
           f.date AS from_date, af.name AS from_account_name, af.number_masked AS from_account_number,
           f.description AS from_description, f.amount_normalized AS from_amount,
           t.date AS to_date, at.name AS to_account_name, at.number_masked AS to_account_number,
           t.description AS to_description, t.amount_normalized AS to_amount
    FROM transfer_links l
    JOIN transactions f ON f.id = l.from_transaction_id
    JOIN accounts af ON af.id = f.account_id
    LEFT JOIN classifications c ON c.transaction_id = f.id
    LEFT JOIN transactions t ON t.id = l.to_transaction_id
    LEFT JOIN accounts at ON at.id = t.account_id
    ORDER BY f.date DESC
    """
    out = []
    for r in conn.execute(sql):
        d = dict(r)
        d["from_account"] = account_label(d.pop("from_account_name"), d.pop("from_account_number"))
        to_name, to_number = d.pop("to_account_name"), d.pop("to_account_number")
        d["to_account"] = account_label(to_name, to_number) if to_name else None
        out.append(d)
    return out


def coverage(rows: list[dict], months: list[str]) -> dict:
    """How much of the P&L outflow in `months` has a real category (SPEC Phase 2 acceptance)."""
    outflows = [r for r in rows if r["month"] in months and r["amount"] < 0 and r["line"] in PNL_OUTFLOW_LINES]
    done = [r for r in outflows if r["category_id"] != UNCATEGORIZED]
    total_value = -sum(r["amount"] for r in outflows)
    done_value = -sum(r["amount"] for r in done)
    return {
        "months": months,
        "count": len(outflows), "count_done": len(done),
        "pct_count": round(100 * len(done) / len(outflows), 1) if outflows else 100.0,
        "value": round(total_value, 2), "value_done": round(done_value, 2),
        "pct_value": round(100 * done_value / total_value, 1) if total_value else 100.0,
    }


def review_queue(rows: list[dict], threshold: float) -> list[dict]:
    """Uncategorized and low-confidence transactions, largest amounts first."""
    queue = [r for r in rows
             if r["category_id"] == UNCATEGORIZED or (r["source"] != "manual" and (r["confidence"] or 0) < threshold)]
    return sorted(queue, key=lambda r: -abs(r["amount"]))


# --- overview helpers (pure; used by the Overview and Month pages) -------------------------------

def line_totals(table: list[dict], months: list[str]) -> dict[str, float]:
    """{P&L line: signed total over `months`} from a `pnl()` table."""
    return {r["key"]: round(sum(r.get(m, 0.0) for m in months), 2) for r in table if r["level"] == 0}


def breakdown(table: list[dict], line: str, months: list[str]) -> list[tuple[str, str, float]]:
    """[(key, label, positive amount)] of a line's components over `months`, largest first.

    Outflow lines are flipped to positive; components that net to the wrong sign (e.g. a month
    where refunds exceed spending in a category) are dropped, since a share cannot be negative.
    """
    sign = 1 if line == "income" else -1
    items = []
    for r in table:
        if r["level"] == 1 and r["line"] == line:
            value = round(sign * sum(r.get(m, 0.0) for m in months), 2)
            if value > 0.005:
                items.append((r["key"], r["label"], value))
    return sorted(items, key=lambda i: -i[2])


def stable_slots(items: list[tuple[str, str, float]], n_slots: int) -> dict[str, int]:
    """Fixed color slot per category, by its all-time rank, so a color always means the same thing."""
    return {key: i for i, (key, _, _) in enumerate(items[:n_slots])}


def binance_holdings(conn: sqlite3.Connection) -> dict | None:
    """Latest Binance positions snapshot: total BRL and BRL value per asset (largest first)."""
    snap = conn.execute("SELECT MAX(snapshot_at) FROM binance_positions").fetchone()[0]
    if snap is None:
        return None
    by_asset: dict[str, float] = defaultdict(float)
    for r in conn.execute("SELECT asset, brl_value FROM binance_positions WHERE snapshot_at = ?", (snap,)):
        by_asset[r[0]] += r[1] or 0.0
    items = sorted(by_asset.items(), key=lambda kv: -kv[1])
    return {"snapshot_at": snap, "total_brl": sum(v for _a, v in items), "by_asset": items}
