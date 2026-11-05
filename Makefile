# One command for every quality gate: `make check` (run before committing).
# Python via `uv run`; web via npm in web/. Nothing here talks to Pluggy or Binance.

.PHONY: check py-lint py-types py-test web-lint web-test web-build api-schema fix

check: py-lint py-types py-test web-lint web-test web-build api-schema
	@echo "All checks passed."

py-lint:
	uv run ruff check src tests

py-types:
	uv run mypy

py-test:  ## tests + branch coverage (fails under 85%, see [tool.coverage] in pyproject.toml)
	uv run pytest -q --cov

web-lint:
	npm --prefix web run lint

web-test:
	npm --prefix web test

web-build:  ## tsc -b, vite build and the no-external-URL bundle check
	npm --prefix web run build

api-schema:  ## web/src/api/schema.d.ts must match the FastAPI models (regenerates it if not)
	@cp web/src/api/schema.d.ts .schema.before.d.ts
	@npm --prefix web run --silent gen:api >/dev/null
	@cmp -s .schema.before.d.ts web/src/api/schema.d.ts; status=$$?; rm -f .schema.before.d.ts; \
		if [ $$status -ne 0 ]; then echo "schema.d.ts was stale: regenerated, review and commit it."; exit 1; fi

fix:  ## safe autofixes (ruff); review the diff afterwards
	uv run ruff check --fix src tests
