"""Classification pipeline. First match wins:

1. manual (stored in `classifications`, never overwritten)
2. transfer detector (transfers.py)
3. user rules (config/rules.yaml)
4. Pluggy category map (config/categories.yaml)
5. uncategorized (no row in `classifications`) -> review queue
"""

import fcntl
import os
import re
import sqlite3
import tempfile
import threading
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from finance.binance_normalize import ACCOUNT_ID as BINANCE_ACCOUNT
from finance.binance_normalize import is_unpriced
from finance.config import CONFIG_DIR, readable_config, writable_config
from finance.transfers import detect, fold

UNCATEGORIZED = "uncategorized"
UNPRICED_CONFIDENCE = 0.5  # Binance rows with no BRL price go to the review queue


@dataclass
class Taxonomy:
    lines: dict[str, str]                     # line id -> label
    categories: dict[str, dict]               # leaf id -> {"line", "label", ...flags}
    pluggy_map: dict[str, dict]               # pluggy name -> {"in", "out", "confidence"}
    settings: dict = field(default_factory=dict)

    def line_of(self, category_id: str) -> str | None:
        return self.categories.get(category_id, {}).get("line")


@dataclass
class Rule:
    id: str
    category: str
    priority: int
    confidence: float
    conditions: dict


def load_taxonomy(path: Path = CONFIG_DIR / "categories.yaml") -> Taxonomy:
    data = yaml.safe_load(readable_config(path).read_text())
    categories: dict[str, dict] = {}
    for line, leaves in data["categories"].items():
        if line not in data["pnl_lines"]:
            raise ValueError(f"categories.yaml: unknown P&L line {line!r}")
        for leaf, attrs in leaves.items():
            if leaf in categories:
                raise ValueError(f"categories.yaml: duplicate category id {leaf!r}")
            categories[leaf] = {"line": line, **(attrs or {})}
    default_conf = data.get("pluggy_map_confidence", 0.7)
    pluggy_map = {}
    for name, target in (data.get("pluggy_map") or {}).items():
        entry = {"in": target, "out": target} if isinstance(target, str) else dict(target)
        entry.setdefault("confidence", default_conf)
        for direction in ("in", "out"):
            if entry.get(direction) and entry[direction] not in categories:
                raise ValueError(f"categories.yaml: pluggy_map {name!r} -> unknown category {entry[direction]!r}")
        pluggy_map[name] = entry
    return Taxonomy(data["pnl_lines"], categories, pluggy_map, data.get("settings") or {})


def load_rules_config(path: Path = CONFIG_DIR / "rules.yaml") -> dict:
    return yaml.safe_load(readable_config(path).read_text()) or {}


def parse_rules(config: dict, taxonomy: Taxonomy) -> list[Rule]:
    rules = []
    seen = set()
    for i, raw in enumerate(config.get("rules") or []):
        raw = dict(raw)
        rule_id = raw.pop("id", None) or f"rule_{i + 1}"
        if rule_id in seen:
            raise ValueError(f"rules.yaml: duplicate rule id {rule_id!r}")
        seen.add(rule_id)
        category = raw.pop("category")
        if category not in taxonomy.categories:
            raise ValueError(f"rules.yaml: rule {rule_id!r} -> unknown category {category!r}")
        rules.append(Rule(rule_id, category, int(raw.pop("priority", 0)), float(raw.pop("confidence", 1.0)), raw))
    # Stable sort: higher priority first, file order within the same priority.
    return sorted(rules, key=lambda r: -r.priority)


def _regex(pattern: str, text: str | None) -> bool:
    return text is not None and text != "" and re.search(pattern, text, re.I) is not None


def _as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def rule_matches(rule: Rule, tx: dict, account: dict) -> bool:
    c = rule.conditions
    amount = tx["amount_normalized"]
    if "description" in c and not (_regex(c["description"], tx.get("description"))
                                   or _regex(c["description"], tx.get("description_raw"))):
        return False
    if "counterparty_name" in c and not _regex(c["counterparty_name"], tx.get("counterparty_name")):
        return False
    if "party" in c and not any(_regex(c["party"], tx.get(k)) for k in
                                ("counterparty_name", "merchant_name", "description", "description_raw")):
        return False
    if "counterparty_doc" in c:
        docs = {re.sub(r"\D", "", str(d)) for d in _as_list(c["counterparty_doc"])}
        if (tx.get("counterparty_doc") or "") not in docs:
            return False
    if "merchant" in c and not _regex(c["merchant"], tx.get("merchant_name")):
        return False
    if "account" in c:
        number = re.sub(r"\D", "", account.get("number_masked") or "")
        if not (_regex(c["account"], account.get("name")) or (number and number.endswith(str(c["account"])))):
            return False
    sign = tx.get("direction_amount", amount)  # unpriced Binance rows: the coin amount's sign
    if "direction" in c and c["direction"] != ("in" if sign > 0 else "out"):
        return False
    if "amount_min" in c and abs(amount) < float(c["amount_min"]):
        return False
    if "amount_max" in c and abs(amount) > float(c["amount_max"]):
        return False
    return not ("payment_method" in c and tx.get("payment_method") not in _as_list(c["payment_method"]))


def pluggy_category_for(tx: dict, taxonomy: Taxonomy) -> tuple[str, float] | None:
    entry = taxonomy.pluggy_map.get(tx.get("pluggy_category") or "")
    if not entry:
        return None
    category = entry.get("in" if tx.get("direction_amount", tx["amount_normalized"]) > 0 else "out")
    return (category, float(entry["confidence"])) if category else None


def _my_identity(conn: sqlite3.Connection, my_cpf: str, my_name: str) -> tuple[set[str], list[str]]:
    cpfs = {re.sub(r"\D", "", my_cpf)} - {""}
    names = [my_name] if my_name else []
    for r in conn.execute("SELECT document, full_name FROM identities"):
        if r["document"]:
            cpfs.add(r["document"])
        if r["full_name"]:
            names.append(r["full_name"])
    return cpfs, names


def _load_transactions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT t.*, json_extract(t.raw_json, '$.merchant.businessName') AS merchant_business, "
        "json_extract(t.raw_json, '$.merchant.name') AS merchant_plain FROM transactions t"
    ).fetchall()
    txs = []
    for r in rows:
        tx = dict(r)
        tx.pop("raw_json")
        business, plain = tx.pop("merchant_business"), tx.pop("merchant_plain")
        tx["merchant_name"] = business or plain
        txs.append(tx)
    return txs


def classify_all(conn: sqlite3.Connection, taxonomy: Taxonomy, rules_config: dict,
                 my_cpf: str = "", my_name: str = "") -> dict[str, int]:
    """Re-run the pipeline over every non-manual transaction. Returns counts by source."""
    rules = parse_rules(rules_config, taxonomy)
    accounts = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM accounts")}
    manual = {r["transaction_id"]
              for r in conn.execute("SELECT transaction_id FROM classifications WHERE source = 'manual'")}
    txs = [t for t in _load_transactions(conn) if t["id"] not in manual]

    cpfs, names = _my_identity(conn, my_cpf, my_name)
    detections, links = detect(
        txs, {a: acc["type"] for a, acc in accounts.items()}, cpfs, names,
        rules_config.get("transfers") or {}, rules_config.get("investments") or {},
        {a: acc["item_id"] for a, acc in accounts.items()},
    )
    now = datetime.now(UTC).isoformat(timespec="seconds")
    results: dict[str, tuple] = {d.transaction_id: (d.category_id, "transfer_detector", None, d.confidence)
                                 for d in detections}

    for tx in txs:
        if tx["id"] in results:
            continue
        unpriced = tx["account_id"] == BINANCE_ACCOUNT and is_unpriced(tx)
        if unpriced:
            tx["direction_amount"] = tx["amount"]
        rule = next((r for r in rules if rule_matches(r, tx, accounts[tx["account_id"]])), None)
        if rule:
            results[tx["id"]] = (rule.category, "rule", rule.id,
                                 min(rule.confidence, UNPRICED_CONFIDENCE) if unpriced else rule.confidence)
            continue
        mapped = pluggy_category_for(tx, taxonomy)
        if mapped:
            results[tx["id"]] = (mapped[0], "pluggy_map", None,
                                 min(mapped[1], UNPRICED_CONFIDENCE) if unpriced else mapped[1])
        # else: no row at all = uncategorized

    with conn:
        conn.execute("DELETE FROM classifications WHERE source != 'manual'")
        conn.execute("DELETE FROM transfer_links")
        # The DELETE holds the write lock: re-read the manual set so a manual save made while we computed wins.
        late = {r["transaction_id"] for r in conn.execute(
            "SELECT transaction_id FROM classifications WHERE source = 'manual'")} - manual
        if late:
            manual |= late
            results = {k: v for k, v in results.items() if k not in late}
            links = [l for l in links if l.from_id not in late and l.to_id not in late]
            txs = [t for t in txs if t["id"] not in late]
        conn.executemany(
            "INSERT INTO classifications (transaction_id, category_id, source, rule_id, confidence, classified_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(tx_id, cat, src, rule_id, conf, now) for tx_id, (cat, src, rule_id, conf) in results.items()],
        )
        conn.executemany(
            "INSERT INTO transfer_links (from_transaction_id, to_transaction_id, link_type, created_at) "
            "VALUES (?, ?, ?, ?)",
            [(l.from_id, l.to_id, l.link_type, now) for l in links],
        )

    counts: dict[str, int] = {"manual": len(manual), "uncategorized": len(txs) - len(results)}
    for _, src, _, _ in results.values():
        counts[src] = counts.get(src, 0) + 1
    return counts


def set_manual(conn: sqlite3.Connection, transaction_id: str, category_id: str, taxonomy: Taxonomy) -> None:
    """Manual classification: always wins and is never overwritten by `classify_all`."""
    if category_id not in taxonomy.categories:
        raise ValueError(f"unknown category {category_id!r}")
    with conn:
        conn.execute(
            "INSERT INTO classifications (transaction_id, category_id, source, rule_id, confidence, classified_at) "
            "VALUES (?, ?, 'manual', NULL, 1.0, ?) ON CONFLICT(transaction_id) DO UPDATE SET "
            "category_id = excluded.category_id, source = 'manual', rule_id = NULL, confidence = 1.0, "
            "classified_at = excluded.classified_at",
            (transaction_id, category_id, datetime.now(UTC).isoformat(timespec="seconds")),
        )


GENERIC_PREFIXES = re.compile(
    r"^(pix (enviado|recebido)( de| para)?|pagamento de pix qr code|pagamento de boleto|compra d[ée]bito|"
    r"envio transfer[êe]ncia|recebimento transfer[êe]ncia|ted enviada|d[ée]bito autom[áa]tico)\s*", re.I)


def suggest_rule(tx: dict, category_id: str) -> dict:
    """Rule pre-filled from a transaction: company CNPJ if present, else a name/description pattern.

    CPFs are never used, so personal documents stay out of rules.yaml.
    """
    rule: dict = {"id": "", "category": category_id, "direction": "in" if tx["amount"] > 0 else "out"}
    doc = tx.get("counterparty_doc") or ""
    text = (tx.get("counterparty_name") or tx.get("merchant_name")
            or GENERIC_PREFIXES.sub("", tx.get("description") or ""))
    text = re.sub(r"\s*\d{1,2}/\d{1,2}$", "", text).strip()  # installment suffix "03/10"
    if len(doc) == 14:
        rule["counterparty_doc"] = doc
        rule["comment"] = text
    else:
        rule["party"] = re.escape(text[:40]).replace("\\ ", " ")  # spaces need no escaping
    base = re.sub(r"[^a-z0-9]+", "_", fold(text)).strip("_")
    rule["id"] = (base[:30] or "rule") + "_" + rule["direction"]
    return rule


_RULES_THREAD_LOCK = threading.Lock()


@contextmanager
def _rules_lock(path: Path) -> Iterator[None]:
    """Serialize read-modify-write of a rules file across threads (API threadpool) and processes (CLI)."""
    with _RULES_THREAD_LOCK, open(path.with_name(f".{path.name}.lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _write_atomic(path: Path, text: str) -> None:
    """Write via a temp file + rename, so a reader sees the old file or the new one, never a truncated one."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _validated(text: str, taxonomy: Taxonomy) -> dict:
    """Parse rules text in memory; any problem is a ValueError (the file is never written)."""
    try:
        config = yaml.safe_load(text) or {}
        parse_rules(config, taxonomy)
    except ValueError:
        raise
    except Exception as e:  # YAML errors, a rule without a category (KeyError), ...
        raise ValueError(f"rules.yaml: invalid result: {type(e).__name__}: {e}") from e
    return config


def _one_line(text: str) -> str:
    """A YAML comment must stay on one line: drop control/format chars, fold every kind of line break."""
    text = "".join(" " if unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") else c for c in text)
    return " ".join(text.split())


def append_rule(rule: dict, taxonomy: Taxonomy, path: Path = CONFIG_DIR / "rules.yaml") -> str:
    """Append a rule to rules.yaml as text (keeps the file's comments). Returns the rule id used.

    The id is made unique. The new text is validated in memory and written atomically under a lock."""
    rule = {k: v for k, v in rule.items() if v not in (None, "")}
    comment = _one_line(str(rule.pop("comment", None) or ""))
    path = writable_config(path)
    with _rules_lock(path):
        original = path.read_text()
        existing = {r.get("id") for r in (yaml.safe_load(original) or {}).get("rules") or []}
        rule_id, n = rule["id"], 2
        while rule_id in existing:
            rule_id, n = f"{rule['id']}_{n}", n + 1
        block = yaml.safe_dump([{**rule, "id": rule_id}], allow_unicode=True, sort_keys=False, width=1000)
        lines = [f"  {line}" for line in block.rstrip("\n").split("\n")]
        if comment:
            lines.insert(1, f"    # {comment}")
        text = original.rstrip("\n") + "\n\n" + "\n".join(lines) + "\n"
        _validated(text, taxonomy)
        _write_atomic(path, text)
    return rule_id


_RULES_KEY = re.compile(r"^rules\s*:\s*(#.*)?$")
_ITEM_START = re.compile(r"^( *)-(?: +|$)")
_ID_KEY = re.compile(r"^ *(?:- +)?id\s*:\s*(.+?)\s*$")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _rule_blocks(lines: list[str]) -> list[tuple[int, int, str | None]]:
    """[(start, end, id)] of the list items under the top-level `rules:` key (end exclusive).

    A block is the `- ` line plus every following line indented deeper than the dash, plus the blank lines
    after it. It ends at the first non-blank line at the dash's indent or less, comments included: a comment
    at item level between two rules (e.g. "  # --- Income ---") heads the next group and is kept."""
    start = next((i for i, line in enumerate(lines) if _RULES_KEY.match(line)), None)
    if start is None:
        return []
    blocks: list[tuple[int, int, str | None]] = []
    item_indent: int | None = None
    i = start + 1
    while i < len(lines):
        line = lines[i]
        if line.strip() and _indent(line) == 0 and not line.startswith("#"):
            break  # next top-level key
        m = _ITEM_START.match(line)
        if m and (item_indent is None or len(m.group(1)) == item_indent):
            item_indent = len(m.group(1))
            key_indent = item_indent + len(m.group(0)) - len(m.group(1))  # column of the item's keys
            j, rule_id = i + 1, None
            head = _ID_KEY.match(line)
            if head and line.lstrip(" ").startswith("-"):
                rule_id = head.group(1)
            while j < len(lines) and (not lines[j].strip() or _indent(lines[j]) > item_indent):
                k = _ID_KEY.match(lines[j])
                if rule_id is None and k and _indent(lines[j]) == key_indent:
                    rule_id = k.group(1)
                j += 1
            if rule_id is not None:
                with suppress(yaml.YAMLError):
                    rule_id = str(yaml.safe_load(rule_id))  # unquote; drops a trailing "# comment"
            blocks.append((i, j, rule_id))
            i = j
            continue
        i += 1
    return blocks


def remove_rule(rule_id: str, path: Path = CONFIG_DIR / "rules.yaml", taxonomy: Taxonomy | None = None) -> bool:
    """Remove the rule `rule_id` from rules.yaml as text (keeps every other line and comment).

    Returns False if no rule has that id. The new text is validated in memory; if it is invalid, or anything
    other than exactly that rule changed, ValueError is raised and the file is not written."""
    taxonomy = taxonomy or load_taxonomy()
    path = writable_config(path)
    with _rules_lock(path):
        original = path.read_text()
        before = [r.get("id") for r in (yaml.safe_load(original) or {}).get("rules") or []]
        if rule_id not in before:
            return False
        lines = original.split("\n")
        block = next((b for b in _rule_blocks(lines) if b[2] == rule_id), None)
        if block is None:
            raise ValueError(f"rules.yaml: could not locate rule {rule_id!r} in the text")
        text = "\n".join(lines[:block[0]] + lines[block[1]:]).rstrip("\n") + "\n"
        try:
            config = _validated(text, taxonomy)
            after = [r.get("id") for r in config.get("rules") or []]
            if after != [i for i in before if i != rule_id]:
                raise ValueError(f"rules.yaml: removing {rule_id!r} changed other rules")
        except ValueError as e:
            raise ValueError(f"rules.yaml: removing {rule_id!r} would leave an invalid file: {e}") from e
        _write_atomic(path, text)
    return True
