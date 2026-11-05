import { useState } from "react";
import { Link, useLocation, useParams } from "react-router";
import { useCategoryPage, useCurrentMonth, useTaxonomy, type CategoryPageResponse } from "../../api/queries";
import { Card } from "../../components/Card";
import { categoryColor, categoryIcon, categoryName } from "../../components/CategoryRow";
import { Skeleton } from "../../components/Skeleton";
import { t } from "../../i18n/pt-BR";
import { brl, brlCompact, monthLabel, monthShort } from "../../lib/format";
import { transacoesLink } from "../../lib/links";
import { apiPeriod, parseKind, singleMonth } from "./period";
import "./panorama.css";

const W = 320;
const H = 130;
const TOP = 14;

function MonthlyBars({ data, color }: { data: CategoryPageResponse; color: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const pts = data.monthly;
  const max = Math.max(1, ...pts.map((p) => p.value), data.usual ?? 0, data.budget ?? 0);
  const y = (v: number) => H - (Math.max(0, v) / max) * (H - TOP);
  const step = W / Math.max(1, pts.length);
  const bw = Math.min(28, step * 0.62);
  const alt = pts.map((p) => `${monthLabel(p.month)}: ${brl(p.value)}`).join("; ");
  const active = hover !== null ? pts[hover] : null;
  return (
    <div className="cat-bars">
      <ul className="legend legend-inline">
        <li><i style={{ background: color }} aria-hidden="true" /><span>{t.panorama.category.monthly}</span></li>
        {data.usual !== null && <li><i className="dash" aria-hidden="true" /><span>{t.panorama.category.usualLine(brl(data.usual))}</span></li>}
        {data.budget !== null && <li><i className="dash budget" aria-hidden="true" /><span>{t.panorama.category.budgetLine(brl(data.budget))}</span></li>}
      </ul>
      <div className="canais-plot" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} className="canais-svg" role="group" aria-label={t.panorama.category.barsAria(data.label)}>
          <title>{`${t.panorama.category.barsAria(data.label)}: ${alt}`}</title>
          {pts.map((p, i) => {
            const x = i * step + (step - bw) / 2;
            const top = y(p.value);
            return (
              <g key={p.month} opacity={hover !== null && hover !== i ? 0.55 : 1}>
                <rect x={x} y={top} width={bw} height={H - top} rx={3} fill={color} />
                <rect x={i * step} y={0} width={step} height={H} fill="transparent" tabIndex={0} role="img" data-testid="cat-bar"
                      aria-label={`${monthLabel(p.month)}: ${brl(p.value)}`} className="canais-hit"
                      onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}
                      onTouchStart={() => setHover(i)} />
              </g>
            );
          })}
          <line x1={0} x2={W} y1={H - 0.5} y2={H - 0.5} stroke="var(--line)" />
          {data.usual !== null && (
            <line data-testid="usual-line" x1={0} x2={W} y1={y(data.usual)} y2={y(data.usual)} stroke="var(--ink)" strokeWidth={1.5}
                  strokeDasharray="5 3" pointerEvents="none" />
          )}
          {data.budget !== null && (
            <line data-testid="budget-line" x1={0} x2={W} y1={y(data.budget)} y2={y(data.budget)} stroke="var(--accent)" strokeWidth={1.5}
                  strokeDasharray="2 3" pointerEvents="none" />
          )}
        </svg>
        {active && hover !== null && (
          <div className={`tooltip${hover === 0 ? " tip-start" : hover === pts.length - 1 ? " tip-end" : ""}`} role="status"
               style={{ left: `${((hover + 0.5) / pts.length) * 100}%` }}>
            <strong>{monthLabel(active.month)} {active.month.slice(0, 4)}</strong>
            <span>{brl(active.value)}</span>
          </div>
        )}
      </div>
      <div className="isb-x" aria-hidden="true">{pts.map((p) => <span key={p.month}>{monthShort(p.month)}</span>)}</div>
    </div>
  );
}

/** One category: monthly bars with the usual / budget reference lines, top counterparties, link to its transactions. */
export function CategoryPage() {
  const { id = "" } = useParams();
  const location = useLocation();
  const kind = parseKind(new URLSearchParams(location.search).get("periodo"));
  const current = useCurrentMonth().data?.month;
  const q = useCategoryPage(id, apiPeriod(kind, current));
  const taxonomy = useTaxonomy();
  const category = taxonomy.data?.categories.find((c) => c.id === id);
  const back = `/panorama?periodo=${kind}`;
  const backLink = <Link to={back} className="back-link">‹ {t.panorama.category.back}</Link>;

  if (!q.data) {
    return (
      <section className="panorama">
        {backLink}
        {q.isError ? (
          <div className="card empty" role="alert">{q.error instanceof Error ? q.error.message : t.genericError}</div>
        ) : (
          <Skeleton height={180} />
        )}
      </section>
    );
  }
  const d = q.data;
  const label = categoryName(id, category) || d.label;
  const link = transacoesLink({ category: id, ...(category ? { line: category.line } : {}) }, { month: singleMonth(kind, current) });
  return (
    <section className="panorama" aria-busy={q.isPlaceholderData}>
      {backLink}
      <h1 className="cat-title">
        <span className="cat-dot" style={{ background: `color-mix(in srgb, ${categoryColor(category)} 18%, var(--card))` }} aria-hidden="true">
          {categoryIcon(id, category)}
        </span>
        {label}
      </h1>
      <p className="sub">{t.panorama.category.total}: {brl(d.total)}</p>
      <Card title={t.panorama.category.monthly}>
        <MonthlyBars data={d} color={categoryColor(category)} />
      </Card>
      <Card title={t.panorama.category.topCounterparties}>
        {d.top_counterparties.length === 0 ? (
          <p className="empty">{t.panorama.category.noCounterparties}</p>
        ) : (
          <ol className="cp-list">
            {d.top_counterparties.map((c) => (
              <li key={c.name}>
                <span className="cp-name">{c.name}<small>{t.panorama.transactionsCount(c.count)}</small></span>
                <b>{brlCompact(c.total)}</b>
              </li>
            ))}
          </ol>
        )}
      </Card>
      <Link to={link} className="pill see-tx">{t.panorama.category.seeTransactions}</Link>
    </section>
  );
}
