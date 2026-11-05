# CLAUDE.md — developer guide

`SPEC.md` describes scope and design; `README.md` has the commands. This file holds conventions and the
technical findings about the Pluggy and Binance APIs that the code relies on.

## Conventions
- Python 3.12+ (pinned 3.13 in `.python-version`), managed with `uv`. Run everything via `uv run ...`.
- Quality gates: `make check` = ruff + mypy + pytest with branch coverage (fails < 85%) + ESLint (typescript-eslint,
  react-hooks) + vitest + production build (incl. no-external-URL check) + `schema.d.ts` drift check. Config in
  `pyproject.toml` / `web/eslint.config.js`. Run it before committing.
- Source in `src/finance/` (installed package `finance`), web app in `web/` (React/TS) served by `finance app`,
  tests in `tests/`.
- CLI: stdlib `argparse` in `src/finance/cli.py`; entry point `finance`.
- HTTP: `httpx`; tests mock it with `respx`.
- Settings: `.env` loaded by `finance.config.load_settings()`; secrets held as `SecretStr`.
- Config: `config/categories.yaml` and `config/rules.yaml` are personal and gitignored. When missing, the app reads
  `config/*.example.yaml` (`config.readable_config`); the first rule written from the app copies the example to
  `rules.yaml` first (`config.writable_config`). Never edit the example from code.
- DB: SQLite at `data/finance.db`, plain SQL via `sqlite3`. `FINANCE_DB` overrides the path.
- Tests never touch `data/` or the personal config: `tests/conftest.py` points `FINANCE_DB` at a temp file and
  closes every SQLite connection a test opened; tests load `tests/fixtures/categories.yaml` and
  `tests/fixtures/rules.yaml` (`samples.CATEGORIES_FIXTURE` / `RULES_FIXTURE`). Only the example-config tests read
  `config/*.example.yaml`.
- Sign convention: inflow to me = positive, outflow = negative (`amount_normalized`).
- Never log secrets, API keys or full account numbers. Fixtures use invented names, documents, numbers and amounts.
- Only external hosts allowed: `api.pluggy.ai`, `api.binance.com` (read-only key, GET only).

## Pluggy findings
- `POST /auth` with `{clientId, clientSecret}` → `{"apiKey": ...}`; send as `X-API-KEY`. The API key lasts 2h.
- No documented endpoint lists all items of an application → item IDs come from `PLUGGY_ITEM_IDS`
  (Dashboard → Applications → app → Demo → Connected Items → copy itemId). MeuPluggy connections show
  connector `MeuPluggy`.
- Transactions: use `GET /v2/transactions` (cursor; `/transactions` is deprecated). No pageSize; pass only the
  `after` value from `next`. Bills/accounts/investments are page-based (`page`/`totalPages`).
- Rate limit 360/min/endpoint; 429 carries `RateLimit-Reset` (seconds).
- History: ~12 months of transactions; 12 bills per card.
- **Dates are UTC timestamps.** Bank txs are mostly `T02:59:59.000Z` / `T03:00:00.000Z`, i.e. local
  (America/Sao_Paulo) midnight or end of day. Convert to UTC-3 before taking the date; `date[:10]` puts most
  transfer legs on different days.
- **Date-only values** (bill `dueDate`, `billClosingDate`) are encoded as exact UTC midnight (`T00:00:00.000Z`);
  keep their calendar day. Real timestamps never land on 00:00:00Z. `normalize.local_date` handles both.
- **Sign convention:** BANK: `DEBIT` → amount < 0, `CREDIT` → amount > 0 (already inflow-positive).
  CREDIT (card): purchases are `DEBIT` with amount **> 0**; payments/refunds are `CREDIT` with amount **< 0**.
  So normalized = amount for BANK, -amount for CREDIT. Use `type` as the tie-breaker.
- `institution`: no such field on accounts. The bank name is in `name`/`marketingName`. Accounts have `owner` +
  `taxNumber`. Two accounts can share a number (checking/savings, or a bank's "conta digital"/"conta
  investimento" pair) without overlapping transactions: not duplicates.
- Pix/TED counterparty: `paymentData.payer` / `paymentData.receiver`, each with `documentNumber
  {type: CPF|CNPJ, value: full digits, unmasked}`, `name` (often null, especially for "me"), `routingNumber`
  (COMPE bank code), `routingNumberISPB`, sometimes branch/account. `paymentMethod`: PIX | TED | TEF | BOLETO |
  OTHER. Card txs have no paymentData. Pluggy's "Same person transfer" txs carry the holder's CPF as payer or
  receiver document, so document matching is reliable.
- `operationType` is richer than paymentMethod: BANK `CARTAO` = debit card purchase ("Compra débito …"),
  `RENDIMENTO_APLIC_FINANCEIRA`, `RESGATE_APLIC_FINANCEIRA`, `APLICACAO_FINANCEIRA`, `TARIFA_SERVICOS_AVULSOS`,
  `CONVENIO_ARRECADACAO`, `OPERACAO_CREDITO`, … CARD: `PAGAMENTO`, `PAGAMENTO_FATURA`, `TARIFA`, `OUTROS`.
- Some banks label incoming transfers with a fee description and a `TARIFA*` op: `payment_method = fee` only for
  outflows.
- **Installments:** one tx per installment, `creditCardMetadata.{installmentNumber,totalInstallments,
  purchaseDate,billId}`, description suffix "NN/TT". POSTED installments are all dated at the **purchase date**
  and carry `billId`; future installments are PENDING, dated in their billing month, no billId. Billing month →
  join `billId` to `/bills` dueDate (or `billForecastDate` YYYY-MM when no billId).
- Card status: POSTED = on a closed bill (has billId); PENDING = open bill or future installment.
- **Card bill payment:** checking side `"Pagamento de fatura …"` (category "Credit card payment", op OUTROS) or
  `"Pagamento de boleto <bank>"` (category "Transfer - Bank Slip"). Card side `"PAGAMENTO COM SALDO"` (CREDIT,
  category "Transfers", op OUTROS), `"Pagamento recebido"` (op PAGAMENTO_FATURA), or with op PAGAMENTO like a
  purchase ("PAGAMENTO ON LINE", "PAGTO DEBITO AUTOMATICO"). Card-side payments match a checking debit of the
  same amount within 0–3 days. Bills' `payments[]` list them too (paymentMode BANK_SLIP).
- A "Credit card payment" to a card that is not connected is one-legged: it goes to the review queue.
- Card balance (`accounts.balance`) == sum of PENDING card txs (open bill + future installments), to the cent.
- Bill `totalAmount` == net card charges carrying that `billId` when no partial payment was made before closing.
  Partial prepayments reduce the bill total and payments on the closing day make per-cycle assignment ambiguous,
  so there is no automatic bill reconciliation.
- Open Finance data can contain errors (a phantom row, a missing row) that no API call fixes. Handle them with a
  manual classification `data_error` (excluded from every total) and/or a `manual_entries` row; the balance check
  keeps reporting the raw data. Re-check after the next refresh and remove the correction if the source is fixed.
- **Investments (`/investments`):** `institution` is null on every position (infer it from the item's accounts).
  Types: FIXED_INCOME/CDB, MUTUAL_FUND (FIXED_INCOME_FUND, INVESTMENT_FUND), ETF, EQUITY/STOCK. Value field =
  `balance` (net of tax for CDB/funds: `amount` − `taxes` == `balance`; ETF/STOCK `balance` == `amount` ==
  quantity × value). `amountProfit` is always null. Skip non-ACTIVE positions (TOTAL_WITHDRAWAL has balance 0).
  CDB `date` is unreliable (can be in the future): snapshot-date positions by sync day. Position/account numbers,
  ISIN, CNPJ and `owner` stay inside `investments.raw_json` and are never exposed by the API.
  `GET /investments/{id}/transactions` (page-based) returns BUY/SELL movements per position.
- MeuPluggy proxy items **cannot be refreshed via the API** (no PATCH route); they follow the original connection,
  which auto-updates every 24h. Check `items.last_updated_at`.
- `data/finance.db` holds manual decisions: never delete/rebuild it; use `finance sync --reprocess`.

## Sync
- `normalize.py` holds pure raw→row functions; `sync.py` does I/O. `finance sync --reprocess` rebuilds derived
  columns from stored raw JSON after a normalization change (upsert skips unchanged raw JSON).
- Card (CREDIT) accounts always pull full history (a future installment turns POSTED dated at its old purchase
  date, outside any window). Bank accounts: full history on the first run, then from `--window-days` (default 30)
  before the latest stored transaction, so a gap between syncs is backfilled.
- PENDING rows in the fetched range that Pluggy no longer returns are deleted; one with a manual classification or
  a note moves that decision to its posted row (same account and amount; same installment, else ≤ 7 days apart),
  else it is kept for review.
- `accounts.role` defaults from subtype and is never overwritten by sync.
- payment_method mapping: card account → `card` (bill payment credits → `other`); bank: PIX → `pix`;
  TED/TEF/DOC/TRANSFERENCIA_MESMA_INSTITUICAO → `ted_doc`; BOLETO/CONVENIO_ARRECADACAO → `boleto`;
  TARIFA* outflows → `fee`; CARTAO ("Compra débito") or "Débito automático" → `debit`; else `other`.
- `bill_month` (YYYY-MM): bill due date via `billId`, else `creditCardMetadata.billForecastDate`.
- `finance sync` ends with a balance check (`checks.py`; skips `'binance'`).
- `pipeline.run_sync(conn, settings, ...)` is the one sync used by `finance sync` and the API; it never raises
  (problems go to `SyncReport.errors/warnings`). Steps: Pluggy banks → Binance → Patrimônio (investments +
  snapshot) → classify.

## Classification
- `config/categories.yaml`: P&L lines (fixed keys), leaf ids, Pluggy map, settings (`review_confidence_below`,
  `tax_provision_rate`). `config/rules.yaml`: transfer/investment detection settings
  + user rules. Leaf ids are what `classifications.category_id` stores.
- Uncategorized = no row in `classifications` (constant `classify.UNCATEGORIZED` is only a label).
- `finance classify` deletes all non-manual classifications and all transfer_links, then recomputes.
- Transfer detector passes: card bill payments (paired, else card-side credit at 0.5) → own transfers (paired;
  needs an own-signal on one leg: my CPF, my name prefix (first 3 words), Pluggy "Same person transfer", or
  `own_account_patterns`) → investment flows (one-legged by nature) → leftover own-signal legs at 0.5. Pairing is
  greedy: closest date, then same payment_method (handles bank → digital account → investment account chains
  where one amount appears several times).
- Month assignment: date month, except card installments (installment_total > 1) → bill_month.
- Coverage metric = P&L outflows (lines 3–4 incl. uncategorized outflows) with a real category.
- "Create rule" appends text to rules.yaml (keeps comments; validated in memory, written atomically under a lock
  file `config/.rules.yaml.lock`; the comment is folded to one line so a merchant name cannot inject YAML) and
  re-runs classify. Rule suggestions never use CPFs, only CNPJs/names. Rules can be deleted via
  `classify.remove_rule` (text edit; refuses if anything else would change).

## Aggregation and insights
- The UI is presentation only; numbers come from `finance.aggregate` / `finance.insights` (pnl, sankey,
  ...). `finance.fmt` formats BRL for the CLI; the web app formats in `web/src/lib/format.ts`.
- Line 2 = `tax_provision_rate` × income in `nf_issued` categories (+ manual tax_provision entries). Manual entries
  always count (no account/method), signed like transactions.
- Line 6 sign: − = money moved into investments (net invested).
- Sankey: inflow/outflow nodes must not share names (cycle); left total = middle total = right total to the cent;
  "Sobrou/Reservas" = line 5; each node carries a `filter` (drill-down to Transações). Own transfers stay out.
- Periods: `month:YYYY-MM`, `last12` (12 calendar months ending at the current month, zero-filled), `year:YYYY`
  (up to the current month). The current month comes from the server, not the browser.
- Account labels must be unique (two accounts can share name and number): use `aggregate.account_labels`.
- `networth.py`: groups `accounts`, `investments`, `crypto`, `cards` (owed = negative). A snapshot row is written
  only for a group whose source succeeded that day (a failed source is never stored as 0); `history` carries the
  last known value forward.

## Binance
See `docs/binance.md` (endpoints, windows, rate limits, pricing, row ids). Account/item id `'binance'`; row ids
`binance:dep|wd|fiat|earn:...`; `amount` = coin units, `amount_normalized` = BRL at the local day's close.

## Web app
- `finance app` = uvicorn on 127.0.0.1:8600 serving `create_app(static_dir=web/dist)`; Vite dev server 5173
  proxies `/api` to 8600.
- API (`src/finance/api/`): routes under `/api/v1`; every route takes the `Workspace` dependency
  (`deps.get_workspace`: one connection per request, cached taxonomy/settings; tests override via
  `create_app(workspace_factory=...)`). Routes and the front end never compute P&L.
- Security: `TrustedHostMiddleware` (localhost/127.0.0.1); mutations need `X-Finance-Client: web`, a local
  `Origin` if present, and a JSON body (else 403/415); every `/api` request with `Sec-Fetch-Site` other than
  `same-origin`/`none` is 403; every response carries CSP (`script-src 'self'`, `frame-ancestors 'none'`),
  `X-Frame-Options: DENY`, nosniff, CORP/COOP same-origin (`api/security.py`); no CORS; no OpenAPI/docs routes.
  Request bounds in `api/validation.py` (amounts finite, |x| ≤ R$ 100 mi; notes ≤ 500 chars, no control
  chars/lone surrogates), checked before anything is written. Errors are always `{error, code}` with a pt-BR
  message (`api/errors.py`). Responses never carry `raw_json`, CPF/CNPJ documents or full account numbers. The
  bundle must not reference external URLs (build check).
- `SyncRunner` (`api/sync_runner.py`): one run at a time in a background thread with its own connection; a second
  start returns 409 `sync_running`. No write transaction is held across network calls; SQLite busy timeout 15 s
  (`db.BUSY_TIMEOUT_S`).
- Theme: `data-theme` attribute on `<html>` (claro/escuro/sistema); a test checks the light and dark token sets
  stay in parity. Charts offer a visually hidden table (`.sr-only` wrapper) as text alternative. Category colors
  follow the category via `aggregate.stable_slots` (all-time rank); Uncategorized/Other stay gray.

## Migrations
- `MIGRATIONS` in `db.py` is index-based: always append. `migrate` runs under `BEGIN IMMEDIATE`, each migration
  and its `user_version` in one transaction; `cmd_app` connects (and migrates) before serving.
- Never open `data/finance.db` from a branch with newer migrations (`connect()` migrates it): copy it to `$TMPDIR`
  and set `FINANCE_DB`. Back it up before the first run after merging a migration.

## On-device suggestions (Swift helper)
- `tools/fm-classify/main.swift` reads JSONL {id, instructions, prompt, categories} → JSONL {id, category}.
  Runtime `DynamicGenerationSchema` (anyOf over category *labels*), greedy sampling, fresh session per item.
  Built by `llm.ensure_helper()` with `xcrun swiftc` into `build/` (gitignored); exit 2 = model unavailable.
- `llm.py` builds prompts: keyword guide + allowed categories by direction (out: lines 3–4, in: line 1) + up to 4
  similar past rule/manual classifications (shared words). Stored in `llm_suggestions`, keyed by PROMPT_VERSION;
  bump it when the prompt changes. Transfer-detector items are never sent. Suggest-only, never automatic.
