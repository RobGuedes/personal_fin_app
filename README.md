# Personal Finance Local MVP

Local tool that pulls transactions from Pluggy (Meu Pluggy / Open Finance) into SQLite and
shows a monthly P&L. See `SPEC.md` for scope.

## Setup

```bash
uv sync                      # creates .venv and installs deps (Python 3.12+)
cp .env.example .env         # then fill PLUGGY_CLIENT_ID / PLUGGY_CLIENT_SECRET (optional: BINANCE_API_KEY / BINANCE_API_SECRET, read-only key)
```

## Configuration

Classification is driven by two YAML files in `config/`:

- `categories.yaml`: the category tree mapped to the P&L lines, the Pluggy category map and settings
  (tax provision rate, review threshold).
- `rules.yaml`: transfer/investment detection settings and your classification rules.

Both are personal and gitignored. Only the templates `config/categories.example.yaml` and
`config/rules.example.yaml` are committed. While a real file is missing, the app and CLI read its
`.example` template, and the first rule you create or delete from the app copies `rules.example.yaml` to
`rules.yaml` before writing. To start customizing right away:

```bash
cp config/categories.example.yaml config/categories.yaml
cp config/rules.example.yaml config/rules.yaml
```

Tests never read either file: they use `tests/fixtures/`.

## Commands

```bash
uv run finance probe         # Phase 0: last 90 days, raw JSON to data/raw/<timestamp>/ (--days N, --full-history)
uv run finance sync          # pull into data/finance.db (full history first, then last 30 days) + balance check
uv run finance sync --skip-binance   # Pluggy only (by default Binance syncs after Pluggy)
uv run finance sync --reprocess  # rebuild derived columns from stored raw JSON, no API calls
uv run finance classify      # re-run transfers + rules + Pluggy map; prints coverage and review queue
                             # edit config/rules.yaml and config/categories.yaml (see Configuration), then re-run
uv run finance suggest       # on-device (Apple Foundation Models) category suggestions for the review queue
uv run finance suggest --evaluate 60   # measure suggestion accuracy on known transactions
uv run pytest                # tests
```

## Web app (Phase 5)

Local web app: FastAPI JSON API (`/api/v1`) + React/TypeScript front end in `web/`, both served on
127.0.0.1 only. Sections (pt-BR): Início, Panorama, Transações, Revisar, Patrimônio, Ajustes (sync, manual entries, rules,
transfer audit, appearance). The sync can be started from the app (Ajustes › Sincronização).

```bash
npm --prefix web ci          # once (and after web/package-lock.json changes)
npm --prefix web run build   # builds web/dist (fails if the bundle references an external URL)
uv run finance app           # http://127.0.0.1:8600, opens the browser (--port N, --no-open)
```

Dev mode (hot reload): run `uv run finance app --no-open` in one terminal and `npm --prefix web run dev`
in another, then open http://127.0.0.1:5173 (Vite proxies `/api` to port 8600). Front-end tests:
`npm --prefix web test`.

The P&L uses the competence view: card purchases count in their transaction month, installments in
the month they are billed. After changing code in `src/finance/`, restart `finance app`.

## On-device suggestions

`finance suggest` (or the button in Revisar) asks Apple's on-device model — via the small
Swift helper in `tools/fm-classify/`, compiled automatically with the Command Line Tools into `build/` —
to suggest a category for each review-queue item. Nothing leaves the Mac. Suggestions are never applied
until you tick Accept and save. Requires macOS 26+ with Apple Intelligence on.
