"""On-device category suggestions for the review queue (Apple Foundation Models via a Swift helper).

Privacy: the model runs on this Mac; nothing is sent anywhere. Suggestions are stored in
`llm_suggestions` and never applied automatically — the user accepts them in the review queue,
which turns them into manual classifications.
"""

import json
import random
import re
import sqlite3
import subprocess
from datetime import UTC, datetime

from finance.classify import UNCATEGORIZED, Taxonomy
from finance.config import PROJECT_ROOT
from finance.transfers import fold

HELPER_SRC = PROJECT_ROOT / "tools" / "fm-classify" / "main.swift"
HELPER_BIN = PROJECT_ROOT / "build" / "fm-classify"
PROMPT_VERSION = 3
UNSURE = "Unsure"

INSTRUCTIONS = """You classify personal bank and credit-card transactions from Brazil. Descriptions are in Portuguese.
Pick the single best category from the allowed list. Answer "Unsure" when the text does not say what the money was for
(for example a Pix to a person's name with no other clue).
Keyword guide:
- posto, combustivel, Shell, Ipiranga, Uber, 99, estacionamento, pedagio, Sem Parar -> Transport & fuel
- restaurante, lanchonete, cafe, bar, pizzaria, sorvete, doceria, iFood, Rappi -> Restaurants & delivery
- supermercado, mercado, atacadao, hortifruti, acougue, carnes, padaria, panificadora -> Groceries
- farmacia, drogaria, Raia, clinica, laboratorio, hospital, medico, dentista -> Health
- escola, colegio, curso, faculdade, livraria escolar -> Education
- agua, saneamento, luz, energia, Vivo, Claro, Tim, internet, gas -> Utilities
- aluguel, condominio, financiamento imobiliario -> Housing
- oficina, pecas, pneu, auto center, lava car -> Car
- tarifa, anuidade, juros, IOF -> Bank fees & interest
- IPTU, IPVA, DARF, DAS, prefeitura -> Taxes paid
- Netflix, Spotify, Google, Apple, Microsoft, Amazon Prime, assinatura, software -> Subscriptions & software
- barbearia, salao, cabeleireiro, manicure, estetica -> Personal care
- loja, magazine, Mercado Livre, Shopee, Amazon, roupas, calcados -> Shopping
Past transactions of this person, when given, show how they like things classified; follow them when they fit."""

GENERIC_WORDS = {"pix", "pagamento", "enviado", "recebido", "compra", "debito", "credito", "code", "qr", "de",
                 "da", "do", "para", "ltda", "s/a", "sa", "me", "eireli", "transferencia", "envio", "recebimento",
                 "br", "com", "parcela", "boleto"}


def helper_ready() -> bool:
    """True when the compiled helper exists and is newer than its source (no compilation needed)."""
    return HELPER_BIN.exists() and HELPER_BIN.stat().st_mtime >= HELPER_SRC.stat().st_mtime


def ensure_helper() -> None:
    """Compile the Swift helper with the Command Line Tools if missing or out of date."""
    if HELPER_BIN.exists() and HELPER_BIN.stat().st_mtime >= HELPER_SRC.stat().st_mtime:
        return
    HELPER_BIN.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["xcrun", "swiftc", "-O", str(HELPER_SRC), "-o", str(HELPER_BIN)], check=True,  # noqa: S603, S607 fixed argv, Xcode tool
                   capture_output=True, text=True)


def allowed_categories(direction: str, taxonomy: Taxonomy) -> dict[str, str]:
    """{label: category id} the model may choose from, by direction of the money."""
    lines = ("income",) if direction == "in" else ("commissions", "expenses")
    allowed = {attrs.get("label", cid): cid for cid, attrs in taxonomy.categories.items() if attrs["line"] in lines}
    allowed[UNSURE] = UNCATEGORIZED
    return allowed


def _tokens(tx: dict) -> set[str]:
    text = fold(f"{tx.get('description') or ''} {tx.get('counterparty_name') or ''} {tx.get('merchant_name') or ''}")
    return {w for w in re.findall(r"[a-z]{3,}", text) if w not in GENERIC_WORDS}


def similar_examples(tx: dict, labeled: list[dict], k: int = 4, exclude_rule: str | None = None,
                     exclude_same_merchant: bool = False) -> list[dict]:
    """Up to k past transactions sharing the most words with `tx` (same direction).

    `exclude_same_merchant` hides examples with the same words, to evaluate on unseen merchants."""
    words = _tokens(tx)
    if not words:
        return []
    direction = tx["amount"] > 0
    scored = []
    for other in labeled:
        if other["id"] == tx["id"] or (other["amount"] > 0) != direction:
            continue
        if exclude_rule and other.get("rule_id") == exclude_rule:
            continue
        other_words = _tokens(other)
        if exclude_same_merchant and other_words == words:
            continue
        overlap = len(words & other_words)
        if overlap:
            scored.append((overlap, other["date"], other))
    scored.sort(key=lambda s: (-s[0], s[1]), reverse=False)
    seen, out = set(), []
    for _, _, other in scored:
        key = (fold(other["description"]), other["category_id"])
        if key not in seen:
            seen.add(key)
            out.append(other)
        if len(out) == k:
            break
    return out


def build_request(tx: dict, taxonomy: Taxonomy, labeled: list[dict], exclude_rule: str | None = None,
                  exclude_same_merchant: bool = False) -> dict:
    direction = "in" if tx["amount"] > 0 else "out"
    allowed = allowed_categories(direction, taxonomy)
    label_of = {cid: label for label, cid in allowed.items()}
    lines = [
        f"Description: {tx.get('description') or ''}",
        f"Amount: R$ {abs(tx['amount']):.2f} {'received' if direction == 'in' else 'paid'}",
        f"Method: {tx.get('payment_method')}",
    ]
    if tx.get("counterparty_name") or tx.get("merchant_name"):
        lines.append(f"Counterparty: {tx.get('counterparty_name') or tx.get('merchant_name')}")
    if tx.get("pluggy_category"):
        lines.append(f"Bank's own category (often wrong): {tx['pluggy_category']}")
    examples = [e for e in similar_examples(tx, labeled, exclude_rule=exclude_rule,
                                            exclude_same_merchant=exclude_same_merchant)
                if e["category_id"] in label_of]
    if examples:
        lines.append("Similar past transactions of this person:")
        lines += [f"- {e['description']} -> {label_of[e['category_id']]}" for e in examples]
    return {"id": tx["id"], "instructions": INSTRUCTIONS, "prompt": "\n".join(lines), "categories": list(allowed),
            "_allowed": allowed}


def run_helper(requests: list[dict]) -> dict[str, str | None]:
    """{transaction id: category id, or None when unsure/failed}."""
    if not requests:
        return {}
    ensure_helper()
    payload = "\n".join(json.dumps({k: v for k, v in r.items() if not k.startswith("_")}, ensure_ascii=False)
                        for r in requests) + "\n"
    proc = subprocess.run([str(HELPER_BIN)], input=payload, capture_output=True, text=True)  # noqa: S603 our binary
    if proc.returncode == 2:
        raise RuntimeError(f"Apple's on-device model is unavailable: {proc.stderr.strip()}")
    allowed = {r["id"]: r["_allowed"] for r in requests}
    out: dict[str, str | None] = {}
    for line in proc.stdout.splitlines():
        resp = json.loads(line)
        category = allowed.get(resp["id"], {}).get(resp.get("category") or "")
        out[resp["id"]] = None if category in (None, UNCATEGORIZED) else category
    return out


def labeled_rows(rows: list[dict]) -> list[dict]:
    """Trusted examples: manual and rule classifications (one row per transaction)."""
    unique = {r["id"]: r for r in rows if r["source"] in ("manual", "rule")}
    return list(unique.values())


def suggest(conn: sqlite3.Connection, taxonomy: Taxonomy, queue: list[dict], rows: list[dict],
            refresh: bool = False, compile: bool = True) -> dict[str, str | None]:
    """Suggest categories for queue rows not yet suggested (with this prompt version) and store them.

    With compile=False nothing is built: a missing or stale helper means no suggestions."""
    if not compile and not helper_ready():
        return {}
    done = {r[0] for r in conn.execute(
        "SELECT transaction_id FROM llm_suggestions WHERE prompt_version = ?", (PROMPT_VERSION,))}
    # Transfer-detector items (one-legged transfers) are about where money moved, not what it bought.
    todo = [t for t in {t["id"]: t for t in queue}.values()
            if t.get("source") != "transfer_detector" and (refresh or t["id"] not in done)]
    labeled = labeled_rows(rows)
    results = run_helper([build_request(t, taxonomy, labeled) for t in todo])
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with conn:
        conn.executemany(
            "INSERT INTO llm_suggestions (transaction_id, category_id, prompt_version, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(transaction_id) DO UPDATE SET category_id = excluded.category_id, "
            "prompt_version = excluded.prompt_version, created_at = excluded.created_at",
            [(tx_id, cat, PROMPT_VERSION, now) for tx_id, cat in results.items()],
        )
    return results


def stored_suggestions(conn: sqlite3.Connection) -> dict[str, str | None]:
    return {r[0]: r[1] for r in conn.execute("SELECT transaction_id, category_id FROM llm_suggestions")}


def evaluate(taxonomy: Taxonomy, rows: list[dict], n: int = 60, seed: int = 1) -> dict:
    """Accuracy on transactions whose category is already known, as if each merchant were new:
    examples from the same rule or with the same words are hidden."""
    labeled = labeled_rows(rows)
    # Ground truth: anything confidently classified on a P&L line (rules, manual, Pluggy map at >= 0.7).
    pool = list({r["id"]: r for r in rows if r["category_id"] != UNCATEGORIZED
                 and (r["confidence"] or 0) >= 0.7
                 and r["line"] in ("income", "commissions", "expenses")}.values())
    sample = random.Random(seed).sample(pool, min(n, len(pool)))  # noqa: S311 sampling, not crypto
    requests = [build_request(t, taxonomy, labeled, exclude_rule=t.get("rule_id"), exclude_same_merchant=True)
                for t in sample]
    got = run_helper(requests)
    correct = sum(1 for t in sample if got.get(t["id"]) == t["category_id"])
    unsure = sum(1 for t in sample if got.get(t["id"]) is None)
    wrong = len(sample) - correct - unsure
    return {"n": len(sample), "correct": correct, "unsure": unsure, "wrong": wrong,
            "precision": round(100 * correct / max(correct + wrong, 1), 1),
            "details": [(t["description"], t["category_id"], got.get(t["id"])) for t in sample]}
