"""Command-line entry point: `finance probe | sync | classify`."""

import argparse
import sys
from pathlib import Path

from finance.pipeline import run_binance  # noqa: F401  (re-exported)


def cmd_probe(args: argparse.Namespace) -> int:
    from finance.config import load_settings
    from finance.probe import run_probe

    run_probe(load_settings(), days=None if args.full_history else args.days)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    from finance.config import load_settings
    from finance.pipeline import run_sync

    settings = load_settings()
    conn = _connect()
    if args.reprocess:
        from finance.sync import reprocess

        print(f"Reprocessed {reprocess(conn)} transactions from stored raw JSON (no API calls).")
        return 0
    report = run_sync(conn, settings, window_days=args.window_days, skip_binance=args.skip_binance,
                      classify=False)
    result = report.pluggy
    if result is not None:
        print(f"Items synced: {result.items_synced}/{len(settings.pluggy_item_ids)}  "
              f"inserted={result.inserted} updated={result.updated} deleted={result.deleted}")
        for a in result.accounts:
            print(f"  {a['name']} [{a['subtype']}] {a['number']}: {a['mode']}, fetched={a['fetched']} "
                  f"inserted={a['inserted']} updated={a['updated']} unchanged={a['unchanged']} "
                  f"deleted={a['deleted']}")
    for err in report.errors:
        if not err.startswith("Binance:"):
            print(f"  ERROR {err}")

    b = report.binance
    if b is not None:
        from finance.fmt import brl

        print(f"Binance: inserted={b.inserted} updated={b.updated} unchanged={b.unchanged} "
              f"holdings={brl(b.positions_brl)}")
        for w in b.warnings:
            print(f"  WARNING {w}")
        if b.ip_restricted is False:
            print("  WARNING: Binance key is not IP-restricted")
    for err in report.errors:
        if err.startswith("Binance:"):
            print(f"  ERROR {err}")
    errors = report.errors

    from finance.checks import balance_report

    print("\nBalance check:")
    for r in balance_report(conn):
        print(f"  [{'ok' if r['ok'] else '!!'}] {r['account']} ({r['type']}): balance={r['balance']:.2f} "
              f"computed={r['computed']:.2f} txs={r['txs']} | {r['check']}")
    return 1 if errors else 0


def _last_months(n: int) -> list[str]:
    from datetime import date

    today = date.today()
    y, m = today.year, today.month
    months = []
    for _ in range(n):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return sorted(months)


def cmd_classify(args: argparse.Namespace) -> int:
    from finance.aggregate import coverage, ledger, review_queue
    from finance.classify import classify_all, load_rules_config, load_taxonomy
    from finance.config import load_settings

    settings = load_settings()
    conn = _connect()
    taxonomy = load_taxonomy()
    counts = classify_all(conn, taxonomy, load_rules_config(), settings.my_cpf, settings.my_name)
    print("Classified by source: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    print("\nTransfer links:")
    for r in conn.execute(
        "SELECT link_type, to_transaction_id IS NOT NULL AS paired, COUNT(*) n FROM transfer_links "
        "GROUP BY 1, 2 ORDER BY 1, 2 DESC"
    ):
        print(f"  {r['link_type']:<24} {'paired' if r['paired'] else 'one-legged':<10} {r['n']}")

    rows = ledger(conn, taxonomy)
    months = _last_months(args.months)
    print(f"\nLast {args.months} months — where the raw outflows went:")
    print(f"  {'month':<8} {'raw outflows':>14} {'P&L lines 3-4':>14} {'investments':>12} {'excluded':>12}")
    for m in months:
        out = [r for r in rows if r["month"] == m and r["amount"] < 0]

        def total(lines, out=out):
            return sum(r["amount"] for r in out if r["line"] in lines)

        print(f"  {m:<8} {sum(r['amount'] for r in out):>14,.2f} "
              f"{total(('commissions', 'expenses')):>14,.2f} {total(('investments',)):>12,.2f} "
              f"{total(('excluded',)):>12,.2f}")
    print("  (excluded = own transfers, card bill payments, data errors; income-category outflows not shown)")

    cov = coverage(rows, months)
    print(f"\nCoverage of P&L outflows in {months[0]}..{months[-1]}: "
          f"{cov['pct_value']}% by value (R$ {cov['value_done']:,.2f} of {cov['value']:,.2f}), "
          f"{cov['pct_count']}% by count ({cov['count_done']}/{cov['count']})")

    queue = review_queue(rows, taxonomy.settings.get("review_confidence_below", 0.6))
    print(f"\nReview queue: {len(queue)} transactions. Largest {min(args.top, len(queue))}:")
    for r in queue[:args.top]:
        print(f"  {r['date']} {r['amount']:>11,.2f} {r['category_id']:<18} {r['payment_method']:<7} "
              f"{(r['description'] or '')[:48]:<48} | {r['pluggy_category']}")
    return 0


def cmd_suggest(args: argparse.Namespace) -> int:
    from finance import aggregate as agg
    from finance import llm
    from finance.classify import load_taxonomy

    conn = _connect()
    taxonomy = load_taxonomy()
    rows = agg.ledger(conn, taxonomy)
    if args.evaluate:
        result = llm.evaluate(taxonomy, rows, n=args.evaluate)
        print(f"Evaluated {result['n']} already-classified transactions: correct={result['correct']} "
              f"wrong={result['wrong']} unsure={result['unsure']} -> precision {result['precision']}% "
              f"(when it does suggest)")
        for desc, truth, got in result["details"]:
            mark = "ok " if got == truth else ("?  " if got is None else "BAD")
            print(f"  {mark} {(desc or '')[:50]:<50} truth={truth:<22} got={got}")
        return 0
    queue = agg.review_queue(rows, taxonomy.settings.get("review_confidence_below", 0.6))
    results = llm.suggest(conn, taxonomy, queue, rows, refresh=args.refresh)
    made = sum(1 for c in results.values() if c)
    print(f"Review queue: {len(queue)} transactions; new suggestions: {made} (unsure: {len(results) - made}). "
          f"Accept them in Revisar (finance app).")
    return 0


WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def cmd_app(args: argparse.Namespace) -> int:
    import uvicorn

    from finance.api import create_app

    dist = WEB_DIST
    if not (dist / "index.html").exists():
        print("web/dist não encontrado — rode `npm --prefix web run build`")
        return 2
    _connect().close()  # apply pending migrations once, before parallel requests can race for them
    url = f"http://127.0.0.1:{args.port}"
    print(f"Finanças em {url}  (Ctrl+C para parar)")
    if not args.no_open:
        import webbrowser

        webbrowser.open(url)
    uvicorn.run(create_app(static_dir=dist), host="127.0.0.1", port=args.port, access_log=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="finance")
    sub = parser.add_subparsers(dest="command", required=True)
    probe = sub.add_parser("probe", help="Explore the Pluggy API and dump raw JSON")
    probe.add_argument("--days", type=int, default=90, help="transaction window (default 90)")
    probe.add_argument("--full-history", action="store_true", help="fetch all available transactions")
    probe.set_defaults(func=cmd_probe)
    sync = sub.add_parser("sync", help="Pull Pluggy data into SQLite")
    sync.add_argument("--window-days", type=int, default=30, help="trailing re-pull window (default 30)")
    sync.add_argument("--reprocess", action="store_true",
                      help="rebuild derived columns from stored raw JSON instead of calling Pluggy")
    sync.add_argument("--skip-binance", action="store_true", help="do not sync Binance after Pluggy")
    sync.set_defaults(func=cmd_sync)
    classify = sub.add_parser("classify", help="Re-run classification on non-manual rows")
    classify.add_argument("--months", type=int, default=3, help="months in the coverage report (default 3)")
    classify.add_argument("--top", type=int, default=25, help="review-queue rows to print (default 25)")
    classify.set_defaults(func=cmd_classify)
    suggest = sub.add_parser("suggest", help="On-device model suggestions for the review queue")
    suggest.add_argument("--evaluate", type=int, metavar="N", help="measure accuracy on N known transactions")
    suggest.add_argument("--refresh", action="store_true", help="re-suggest transactions already suggested")
    suggest.set_defaults(func=cmd_suggest)
    app = sub.add_parser("app", help="Serve the local web app (API + web/dist) on 127.0.0.1")
    app.add_argument("--port", type=int, default=8600, help="port (default 8600)")
    app.add_argument("--no-open", action="store_true", help="do not open the browser")
    app.set_defaults(func=cmd_app)
    return parser


_opened: list = []  # connections opened by the running command; main() closes them


def _connect():
    from finance.db import connect  # looked up at call time (tests patch finance.db.connect)

    conn = connect()
    _opened.append(conn)
    return conn


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    finally:
        while _opened:
            _opened.pop().close()


if __name__ == "__main__":
    sys.exit(main())
