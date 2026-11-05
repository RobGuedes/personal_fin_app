"""Phase 0 API probe: dump raw Pluggy data and report which fields actually show up."""

import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from finance.config import RAW_DIR, Settings
from finance.pluggy_client import PluggyClient

BILL_PAYMENT_PATTERN = re.compile(r"fatura|pagto|pagamento|pgto|cart[aã]o|card", re.I)


def mask(value: Any, keep: int = 4) -> str:
    """Keep only the last `keep` alphanumerics of an identifier."""
    s = "" if value is None else str(value)
    chars = [c for c in s if c.isalnum()]
    if len(chars) <= keep:
        return "*" * len(chars)
    return "*" * (len(chars) - keep) + "".join(chars[-keep:])


def field_paths(obj: Any, prefix: str = "", depth: int = 3) -> set[str]:
    """Dotted paths of non-null, non-empty leaves (dicts expanded up to `depth`)."""
    paths: set[str] = set()
    if not isinstance(obj, dict) or depth == 0:
        return paths
    for key, val in obj.items():
        path = f"{prefix}{key}"
        if val is None or val == "" or val == [] or val == {}:
            continue
        if isinstance(val, dict) and depth > 1:
            paths |= field_paths(val, path + ".", depth - 1) or {path}
        else:
            paths.add(path)
    return paths


def _dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def run_probe(settings: Settings, days: int | None = 90) -> Path:
    """Fetch everything for each item, save raw JSON, print a summary. Returns the dump dir."""
    if not settings.pluggy_item_ids:
        raise SystemExit(
            "PLUGGY_ITEM_IDS is empty. Find item IDs in dashboard.pluggy.ai → Applications → "
            "your app → Demo → Connected Items."
        )
    out = RAW_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    date_from = date.today() - timedelta(days=days) if days else None

    accounts: list[dict] = []
    txs_by_account: dict[str, list[dict]] = {}
    bills_by_account: dict[str, list[dict]] = {}
    investments: list[dict] = []
    items: list[dict] = []
    identity_found: list[bool] = []

    with PluggyClient(settings) as client:
        for n, item_id in enumerate(settings.pluggy_item_ids, 1):
            item_dir = out / f"item_{n}"
            item = client.get_item(item_id)
            items.append(item)
            _dump(item_dir / "item.json", item)

            identity = client.get_identity(item_id)
            identity_found.append(identity is not None)
            if identity is not None:
                _dump(item_dir / "identity.json", identity)

            item_accounts = client.list_accounts(item_id)
            _dump(item_dir / "accounts.json", item_accounts)
            accounts.extend(item_accounts)

            for acc in item_accounts:
                txs = list(client.iter_transactions(acc["id"], date_from=date_from))
                txs_by_account[acc["id"]] = txs
                _dump(item_dir / f"transactions_{acc['id']}.json", txs)
                if acc.get("type") == "CREDIT":
                    bills = client.list_bills(acc["id"])
                    bills_by_account[acc["id"]] = bills
                    _dump(item_dir / f"bills_{acc['id']}.json", bills)

            item_investments = client.list_investments(item_id)
            _dump(item_dir / "investments.json", item_investments)
            investments.extend(item_investments)

    summary = build_summary(items, accounts, txs_by_account, bills_by_account, investments, identity_found, days)
    _dump(out / "summary.json", summary)
    print_summary(summary)
    print(f"\nRaw JSON saved to {out}")
    return out


def build_summary(
    items: list[dict],
    accounts: list[dict],
    txs_by_account: dict[str, list[dict]],
    bills_by_account: dict[str, list[dict]],
    investments: list[dict],
    identity_found: list[bool],
    days: int | None,
) -> dict:
    acc_by_id = {a["id"]: a for a in accounts}
    summary: dict[str, Any] = {"window_days": days, "items": [], "accounts": [], "by_account_type": {}}

    for item, has_identity in zip(items, identity_found, strict=True):
        summary["items"].append({
            "connector": (item.get("connector") or {}).get("name"),
            "status": item.get("status"),
            "executionStatus": item.get("executionStatus"),
            "lastUpdatedAt": item.get("lastUpdatedAt"),
            "identity_endpoint": has_identity,
            "fields": sorted(field_paths(item, depth=1)),
        })

    for acc in accounts:
        txs = txs_by_account.get(acc["id"], [])
        dates = sorted(t["date"][:10] for t in txs if t.get("date"))
        bills = bills_by_account.get(acc["id"])
        summary["accounts"].append({
            "type": acc.get("type"),
            "subtype": acc.get("subtype"),
            "name": acc.get("name"),
            "marketingName": acc.get("marketingName"),
            "institution": _institution(acc),
            "number": mask(acc.get("number")),
            "currency": acc.get("currencyCode"),
            "balance": acc.get("balance"),
            "transactions": len(txs),
            "first_date": dates[0] if dates else None,
            "last_date": dates[-1] if dates else None,
            "bills": None if bills is None else len(bills),
            "bill_due_range": _range([b.get("dueDate", "")[:10] for b in bills or []]),
            "account_fields": sorted(field_paths(acc, depth=2)),
        })

    grouped: dict[str, list[dict]] = defaultdict(list)
    for acc_id, txs in txs_by_account.items():
        grouped[acc_by_id[acc_id].get("type", "?")].extend(txs)

    for acc_type, txs in grouped.items():
        presence: Counter[str] = Counter()
        for t in txs:
            presence.update(field_paths(t))
        signs = Counter(f"{t.get('type')} / {'+' if (t.get('amount') or 0) >= 0 else '-'}" for t in txs)
        summary["by_account_type"][acc_type] = {
            "count": len(txs),
            "field_presence_pct": {k: round(100 * v / len(txs), 1) for k, v in sorted(presence.items())},
            "type_vs_sign": dict(signs),
            "status": dict(Counter(t.get("status") for t in txs)),
            "top_categories": Counter(t.get("category") for t in txs).most_common(15),
            "payment_methods": dict(Counter((t.get("paymentData") or {}).get("paymentMethod") for t in txs)),
            "examples": _examples(txs),
        }

    summary["investments"] = {
        "count": len(investments),
        "types": dict(Counter(f"{i.get('type')}/{i.get('subtype')}" for i in investments)),
        "total_balance": round(sum(i.get("balance") or 0 for i in investments), 2),
        "fields": sorted(set().union(*(field_paths(i, depth=1) for i in investments))) if investments else [],
    }
    summary["bills_fields"] = sorted(
        set().union(*(field_paths(b, depth=2) for bills in bills_by_account.values() for b in bills))
    ) if any(bills_by_account.values()) else []
    return summary


def _institution(acc: dict) -> str | None:
    # Field name unconfirmed for MeuPluggy accounts; fall back through likely candidates.
    return acc.get("institution") or acc.get("bankName") or acc.get("marketingName")


def _range(values: list[str]) -> list[str] | None:
    values = sorted(v for v in values if v)
    return [values[0], values[-1]] if values else None


def _masked_payment_data(pd: dict | None) -> dict | None:
    """Show paymentData shape with documents/account numbers masked."""
    if not pd:
        return None

    def walk(v: Any, key: str = "") -> Any:
        if isinstance(v, dict):
            return {k: walk(x, k) for k, x in v.items()}
        if key in ("value", "number", "accountNumber", "agency", "branchNumber") and v:
            return mask(v)
        return v

    return walk(pd)


def _examples(txs: list[dict]) -> dict:
    """Small evidence samples for the Phase 0 questions."""
    pix = [t for t in txs if (t.get("paymentData") or {}).get("paymentMethod") == "PIX"]
    installments = [t for t in txs if (t.get("creditCardMetadata") or {}).get("totalInstallments")]
    bill_like = [t for t in txs if BILL_PAYMENT_PATTERN.search(f"{t.get('description')} {t.get('descriptionRaw')}")]

    def brief(t: dict) -> dict:
        return {
            "date": (t.get("date") or "")[:10],
            "description": t.get("description"),
            "descriptionRaw": t.get("descriptionRaw"),
            "amount": t.get("amount"),
            "type": t.get("type"),
            "category": t.get("category"),
            "operationType": t.get("operationType"),
        }

    return {
        "pix": [{**brief(t), "paymentData": _masked_payment_data(t.get("paymentData"))} for t in pix[:3]],
        "installments": [{**brief(t), "creditCardMetadata": t.get("creditCardMetadata")} for t in installments[:4]],
        "bill_payment_like": [brief(t) for t in bill_like[:8]],
        "largest_credits": [brief(t) for t in sorted(txs, key=lambda t: -(t.get("amount") or 0))[:3]],
    }


def print_summary(s: dict) -> None:
    print(f"=== Pluggy probe (window: {s['window_days'] or 'full history'} days) ===\n")
    print("Items:")
    for i in s["items"]:
        print(f"  {i['connector']}: status={i['status']} exec={i['executionStatus']} "
              f"lastUpdatedAt={i['lastUpdatedAt']} identity={'yes' if i['identity_endpoint'] else 'no'}")
    print("\nAccounts:")
    for a in s["accounts"]:
        print(f"  [{a['type']}/{a['subtype']}] {a['name']} ({a['institution']}) {a['number']} "
              f"balance={a['balance']} {a['currency']} | txs={a['transactions']} "
              f"{a['first_date']}..{a['last_date']}"
              + (f" | bills={a['bills']} due {a['bill_due_range']}" if a["bills"] is not None else ""))
    for acc_type, g in s["by_account_type"].items():
        print(f"\n--- Transactions on {acc_type} accounts ({g['count']}) ---")
        print(f"  type vs amount sign: {g['type_vs_sign']}")
        print(f"  status: {g['status']}")
        print(f"  payment methods: {g['payment_methods']}")
        print("  field presence (% of txs):")
        for k, v in g["field_presence_pct"].items():
            print(f"    {v:5.1f}%  {k}")
        print(f"  top categories: {g['top_categories']}")
        for name, rows in g["examples"].items():
            if rows:
                print(f"  examples: {name}")
                for r in rows:
                    print(f"    {json.dumps(r, ensure_ascii=False, default=str)}")
    inv = s["investments"]
    print(f"\nInvestments: {inv['count']} positions, total balance {inv['total_balance']}, types {inv['types']}")
    print(f"  fields: {inv['fields']}")
    print(f"Bill fields: {s['bills_fields']}")
