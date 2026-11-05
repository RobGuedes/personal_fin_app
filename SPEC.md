# Personal Finance Local MVP — Specification

> Read this whole document before writing any code. It is the source of truth for scope, design decisions and acceptance criteria. When something here conflicts with your assumptions about the Pluggy API, **trust the API's actual responses and the official docs, then tell me what differed.**

---

## 1. Context and goal

I am an individual in Brazil (BRL, Portuguese-language bank data) with checking accounts and credit cards at several banks. I connected them to **Meu Pluggy** (free personal tier, Open Finance) and have a **Client ID / Client Secret** from `dashboard.pluggy.ai`.

Today I manage my finances in a spreadsheet structured like a P&L:

1. Income sources
2. Provision for taxes (on invoices / Notas Fiscais I issued)
3. Commissions paid
4. Rough global estimate of expenses
5. **Net income**
6. Investments

**The problem:** I lose track of where the money goes. Line 4 is a single rough number.

**Goal of this MVP:** a local tool that pulls my real transactions (credit cards, Pix, transfers, debits) and shows me, month by month, **where money comes from and where it goes**, organized in the same P&L logic I already use — with line 4 broken down into real categories.

This is **step 1**. A native iOS app comes later, so keep the core logic (data model, classification, aggregation) cleanly separated from the UI.

---

## 2. Non-goals (do NOT build now)

- No mobile app, no auth/multi-user, no deployment, no cloud hosting.
- No LLM-based classification yet (rules first; LLM is a later phase).
- No budgeting, forecasting, alerts or goals.
- No write operations against any bank (Pluggy access is read-only; keep it that way).
- No investment performance analytics. Investments appear only as **cash flows** (money sent to / received from brokerage/investment accounts).

---

## 3. Tech stack

- **Python 3.12+**, dependency management with **uv** (`pyproject.toml`).
- **SQLite** (single file under `data/`), accessed via the standard library or SQLAlchemy Core — keep it simple.
- **httpx** for the Pluggy client.
- **FastAPI + React/TypeScript** (`finance app`, localhost only) for the dashboard (originally Streamlit + Plotly; retired in Phase 5).
- **pydantic** for API response models and config.
- **pytest** for tests.
- Config via `.env` (python-dotenv). Classification rules in a human-editable **YAML** file.

Suggested layout (adjust if you have a good reason, and tell me):

```
.
├── SPEC.md                  # this file
├── CLAUDE.md                # your working notes / conventions (create it)
├── pyproject.toml
├── .env.example             # PLUGGY_*, MY_CPF, MY_NAME, BINANCE_* (placeholders only)
├── .gitignore               # must ignore .env, data/, *.db, raw dumps
├── config/
│   ├── categories.example.yaml  # category tree mapped to P&L lines (copy to categories.yaml, gitignored)
│   └── rules.example.yaml       # classification rules (copy to rules.yaml, gitignored)
├── src/finance/
│   ├── pluggy_client.py     # auth + paginated GETs, retry/backoff
│   ├── sync.py              # pull → upsert into SQLite (idempotent)
│   ├── db.py                # schema + migrations
│   ├── transfers.py         # internal-transfer & card-bill-payment detection
│   ├── classify.py          # rules engine
│   ├── aggregate.py         # monthly P&L / cash-flow queries
│   └── cli.py               # `finance sync`, `finance classify`, `finance probe`
├── src/finance/api/         # FastAPI JSON API (web/ = React front end)
├── data/                    # gitignored: finance.db, raw/ JSON dumps
└── tests/
```

---

## 4. Pluggy integration

### 4.1 What I know (verify everything)
- Base URL `https://api.pluggy.ai`. Authenticate with `POST /auth` using client ID + secret to get a short-lived API key, sent as `X-API-KEY`. Cache it and refresh on expiry/401.
- Data hierarchy: **Item** (one connection) → **Accounts** (checking, savings, credit card) → **Transactions**. Investments hang off the item.
- My accounts were connected via the **MeuPluggy connector**, so my data arrives through one or more items in my Dashboard application. Free tier: up to 5 active connections, same account holder, auto-refresh every 24h.
- Pluggy offers a **documentation MCP** and full API reference at `docs.pluggy.ai`. Use them to confirm endpoints, query parameters, pagination and field names instead of guessing.

### 4.2 Phase 0 deliverable — API probe (do this FIRST)
Build `finance probe`, which:
1. Authenticates.
2. Discovers my items (if there's no list endpoint, read item IDs from `PLUGGY_ITEM_IDS` in `.env` and tell me where to find them in the Dashboard).
3. For each item: fetches the item, its accounts, the last ~90 days of transactions per account, and investments.
4. Saves raw JSON to `data/raw/<timestamp>/…`.
5. Prints a summary: accounts (type/subtype, institution, masked number, balance), transaction counts, date range, and **a report of the fields actually present**, including `type` (DEBIT/CREDIT), amount sign behavior per account type, `category`/`categoryId`, `paymentData` (Pix payer/receiver), `creditCardMetadata` (installments, bill), `merchant`, `descriptionRaw`.

**Stop after Phase 0 and show me the summary.** Explicitly answer:
- What is the sign convention for credit-card transactions vs. checking-account transactions?
- How do Pix transfers expose the counterparty (name, CPF/CNPJ, bank)?
- How do installment purchases (*parcelado*) appear?
- How does a credit-card bill payment appear on the checking side and on the card side?
- How far back does history go?

The answers drive the design of Phases 2 and 3.

---

## 5. Data model (SQLite)

Minimum tables (refine after Phase 0):

- `items` — id, connector name, status, last_updated_at, raw_json.
- `accounts` — id, item_id, type, subtype, name, institution, number_masked, currency, balance, raw_json. Plus a user-editable `role` column: `checking | savings | credit_card | investment | other`.
- `transactions` — id (Pluggy id, primary key), account_id, date, description, description_raw, amount (raw, as returned), **amount_normalized** (see §6.1), currency, type, pluggy_category, pluggy_category_id, counterparty_name, counterparty_doc, payment_method (`card | pix | ted_doc | boleto | debit | fee | other`), installment_number, installment_total, bill_id, raw_json, first_seen_at, updated_at.
- `classifications` — transaction_id, category_id, source (`rule | pluggy_map | transfer_detector | manual`), rule_id, confidence, classified_at. **Manual always wins and is never overwritten.**
- `transfer_links` — pairs of transaction ids identified as the two legs of one internal movement, with link type (`own_transfer | card_bill_payment | investment_contribution | investment_redemption`).
- `manual_entries` — month, P&L line, amount, note. For items that do not come from bank data (see §7, tax provision).
- `sync_runs` — timestamp, items synced, counts inserted/updated, errors.

Sync must be **idempotent** (upsert by Pluggy id) and **incremental** (re-pull a trailing window, e.g. last 30 days, to catch pending → posted changes; first run pulls full available history). Keep raw JSON for every record so we can reprocess without re-fetching.

---

## 6. Core logic

### 6.1 Sign normalization
Define one convention across all accounts: **inflow to me = positive, outflow from me = negative**. Implement it per account type based on the Phase 0 findings, with unit tests using real (anonymized) samples.

### 6.2 Avoid double counting — the most important part
My money moves between my own accounts constantly. A naive sum counts the same real expense twice and makes the numbers useless. Detect and tag:

1. **Credit-card bill payment.** Paying the card bill from checking is NOT an expense. The expense is each individual card purchase. Tag the checking-side payment (and the card-side payment credit, if present) as `card_bill_payment` and exclude them from P&L.
2. **Transfers between my own accounts** (Pix/TED between accounts with the same holder). Match by: opposite amounts, close dates (±2 days, configurable), counterparty doc = my CPF (configurable in `.env` as `MY_CPF`, may be masked in data), or counterparty name matching my name. Tag as `own_transfer`, exclude from P&L.
3. **Investment flows.** Transfers to/from brokerage or investment accounts (configurable list of institutions/counterparties in YAML) are tagged `investment_contribution` / `investment_redemption`. They are excluded from expenses and income and shown on the **Investments** line.

Unmatched one-legged candidates go to a **review queue**, never silently dropped. Include a dashboard view that lists everything excluded as a transfer so I can audit it.

### 6.3 Credit-card timing
Default: a card purchase counts in the **month of the transaction date** (economic/competence view). For installments, each installment counts in the month it is billed. Make the alternative "cash view" (by bill due month) a toggle later. For now, just document which one is used on the dashboard.

### 6.4 Classification
Pipeline, in order, first match wins:
1. **Manual override** (stored in `classifications`, source=manual).
2. **Transfer detector** (§6.2).
3. **User rules** from `config/rules.yaml`. Matching options: regex on description/description_raw, counterparty name, counterparty doc (CPF/CNPJ), merchant, account, amount range, payment method. Each rule has an id, target category and optional priority.
4. **Pluggy category mapping**: a table in `categories.yaml` mapping Pluggy's categories to mine.
5. Otherwise → `uncategorized` (goes to review queue).

Reclassification must be cheap: `finance classify` re-runs the pipeline over all non-manual rows.

Learning loop (simple, no ML): when I manually categorize a transaction in the dashboard, offer to **create a rule** from it (pre-filled with counterparty doc or a description pattern) and append it to `rules.yaml`.

---

## 7. Category tree mapped to my P&L

`config/categories.yaml` (template: `config/categories.example.yaml`) defines a two-level tree. Each leaf maps to exactly one P&L line. Starting point:

| P&L line | Example leaf categories |
|---|---|
| **1. Income** | Salary / pro-labore, Professional services (NF), Dividends & distributions, Reimbursements, Other income |
| **2. Tax provision** | *Computed, not from bank data* — see below |
| **3. Commissions paid** | Referral / partner commissions |
| **4. Expenses** | Housing, Utilities, Groceries, Restaurants & delivery, Transport & fuel, Car, Health, Education, Kids, Personal care, Subscriptions & software, Shopping, Travel, Leisure, Bank fees & interest, Taxes paid (IPTU, IPVA, etc.), Donations, Gifts, Other |
| **5. Net income** | Computed = 1 − 2 − 3 − 4 |
| **6. Investments** | Contributions (negative), Redemptions (positive), Net |
| *(excluded)* | Own transfers, Card bill payments |

**Tax provision (line 2):** taxes on invoices I issue are a provision, not a bank event. Support it via `manual_entries` (monthly amount I type in) **and** an optional config rule: `tax_provision_rate` applied to income in categories flagged `nf_issued: true`. Show both the provision and actual tax payments (DARF/DAS found in bank data) so I can reconcile.

---

## 8. Dashboard (web app, localhost)

Served by `finance app` (127.0.0.1:8600; React front end in `web/`, JSON API in `src/finance/api/`). The original Streamlit
dashboard was retired in Phase 5; the views below now live in these sections:

- **Início / Panorama** — monthly P&L (lines 1–6, drill-down to transactions), where the money goes, by channel, cash-flow Sankey.
- **Transações** — filters (period, account, payment method, category) and search.
- **Revisar** — review queue with inline category assignment and "create rule".
- **Patrimônio** — net worth, investments, crypto holdings.
- **Ajustes** — sync status and "Sync now", manual entries, rules, transfer audit, appearance.

Formatting: BRL (`R$ 1.234,56`), dates `dd/mm/yyyy`. UI labels are in Brazilian Portuguese (pt-BR).

---

## 9. Security and privacy

- Credentials only in `.env`. Never log secrets, API keys or full account numbers.
- `.gitignore` must cover `.env`, `data/`, `*.db`, and raw dumps **before the first commit**.
- Everything stays local. No telemetry, no external calls other than `api.pluggy.ai` and `api.binance.com`.
- Test fixtures must be invented (names, CPF/CNPJ, account numbers, amounts).
- Personal config (`config/rules.yaml`, `config/categories.yaml`) is gitignored; only the `.example` templates are committed.

---

## 10. Phased delivery and acceptance criteria

Work in phases. **Stop at the end of each phase**, summarize what was done, what you learned, and any spec changes you recommend. Wait for my go-ahead.

**Phase 0 — Scaffold + API probe**
- Project skeleton, `.env.example`, `.gitignore`, `CLAUDE.md`.
- `finance probe` works end-to-end and answers the questions in §4.2.

**Phase 1 — Sync to SQLite**
- `finance sync` populates all tables; re-running it creates no duplicates.
- Sign normalization implemented and tested.
- ✅ Each account's computed balance movement is consistent with the reported balances (or discrepancies are explained).

**Phase 2 — Transfers + classification**
- Transfer detector, rules engine, Pluggy category mapping, manual overrides.
- ✅ Card bill payments and own transfers are excluded; a month's total expenses are NOT inflated by them.
- ✅ After my initial rules, ≥ 85% of expense **value** in the last 3 months is categorized (report the % by count and by value).

**Phase 3 — Dashboard**
- All views in §8 (delivered first in Streamlit, now the web app).
- ✅ Monthly P&L reproduces my spreadsheet structure; I can drill from any number down to the underlying transactions.

**Phase 4 — Binance**
- Read-only Binance sync (deposits, withdrawals, fiat, Earn) priced in BRL; see `docs/binance.md`.

**Later phases (not now):** LLM-assisted classification of the review queue, budgets per category, cash vs competence toggle, export to my existing spreadsheet, and porting the core to the iOS app.

---

## 11. Working agreement

- Ask before making architectural changes to this spec; small implementation choices are yours.
- Prefer small, readable modules and plain SQL over clever abstractions.
- Write tests for sign normalization, transfer detection and rule matching.
- When the API surprises you, record it in `CLAUDE.md` under "Pluggy findings".
- Keep `README.md` with the exact commands to set up, sync and run the dashboard.
