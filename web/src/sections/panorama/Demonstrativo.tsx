import { useState } from "react";
import { Link } from "react-router";
import { useTaxonomy, type PnlResponse } from "../../api/queries";
import { t } from "../../i18n/pt-BR";
import { brlInt, monthLabel, monthShort } from "../../lib/format";
import { transacoesLink } from "../../lib/links";

type Row = PnlResponse["rows"][number];

const head = (ym: string, multiYear: boolean) => (multiYear ? `${monthShort(ym)}/${ym.slice(2, 4)}` : monthShort(ym));

/** P&L: lines 1–6 × months + total + average. A line expands to its categories; a category cell opens that month in Transações. */
export function Demonstrativo({ data }: { data: PnlResponse }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const taxonomy = useTaxonomy();
  const known = new Set(taxonomy.data?.categories.map((c) => c.id) ?? []);
  const multiYear = new Set(data.months.map((m) => m.slice(0, 4))).size > 1;
  const toggle = (k: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  if (data.rows.length === 0) return <p className="empty">{t.panorama.empty}</p>;
  const hasChildren = (r: Row) => data.rows.some((c) => c.level === 1 && c.line === r.key);
  const visible = data.rows.filter((r) => r.level === 0 || open.has(r.line));

  return (
    <div className="pnl-scroll">
      <table className="pnl">
        <thead>
          <tr>
            <th scope="col">{t.panorama.line}</th>
            {data.months.map((m) => <th key={m} scope="col" title={`${monthLabel(m)} ${m.slice(0, 4)}`}>{head(m, multiYear)}</th>)}
            <th scope="col">{t.panorama.total}</th>
            <th scope="col">{t.panorama.average}</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((r) => {
            const isLine = r.level === 0;
            const expandable = isLine && hasChildren(r);
            const expanded = open.has(r.key);
            const linkable = !isLine && known.has(r.key);
            return (
              <tr key={`${r.level}:${r.line}:${r.key}`} className={isLine ? "is-line" : "is-cat"}>
                <th scope="row">
                  {expandable ? (
                    <button type="button" aria-expanded={expanded}
                            aria-label={expanded ? t.panorama.collapse(r.label) : t.panorama.expand(r.label)}
                            onClick={() => toggle(r.key)}>
                      <span aria-hidden="true" className="chev">{expanded ? "▾" : "▸"}</span>
                      {r.label}
                    </button>
                  ) : (
                    <span className={isLine ? "" : "indent"}>{r.label}</span>
                  )}
                </th>
                {data.months.map((m) => {
                  const v = r.values[m] ?? 0;
                  return (
                    <td key={m} className={v < 0 ? "neg" : undefined}>
                      {linkable && Math.round(v) !== 0 ? (
                        <Link to={transacoesLink({ category: r.key, line: r.line }, { month: m })}
                              aria-label={t.panorama.cellLabel(r.label, monthLabel(m), brlInt(v))}>
                          {brlInt(v)}
                        </Link>
                      ) : brlInt(v)}
                    </td>
                  );
                })}
                <td className="tot">{brlInt(r.total)}</td>
                <td>{brlInt(r.average)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
