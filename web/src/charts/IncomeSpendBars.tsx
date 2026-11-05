import { scaleBand, scaleLinear } from "d3-scale";
import { useState } from "react";
import type { components } from "../api/schema";
import { t } from "../i18n/pt-BR";
import { brl, brlCompact, monthLabel, monthShort } from "../lib/format";

export type TrendPoint = components["schemas"]["TrendPoint"];

const W = 320;
const H = 96;
const GAP = 2;
const R = 4;

/** Bar with 4px rounded top corners, anchored on the baseline. */
function barPath(x: number, w: number, top: number, bottom: number): string {
  const h = bottom - top;
  if (h <= 0) return "";
  const r = Math.min(R, w / 2, h);
  return `M${x},${bottom}V${top + r}Q${x},${top} ${x + r},${top}H${x + w - r}Q${x + w},${top} ${x + w},${top + r}V${bottom}Z`;
}

/** Grouped bars per month: Renda (line 1) vs Gastos (lines 2–4); the selected month is highlighted. */
export function IncomeSpendBars({ points, current }: { points: TrendPoint[]; current: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const x = scaleBand<string>().domain(points.map((p) => p.month)).range([0, W]).paddingInner(0.3).paddingOuter(0.15) // outer = inner/2: band centers sit at (i + 0.5) * step, under the HTML labels;
  const max = Math.max(1, ...points.map((p) => Math.max(p.income, p.spending)));
  const y = scaleLinear().domain([0, max]).range([H, 6]);
  const bw = (x.bandwidth() - GAP) / 2;
  const active = hover !== null ? points[hover] : null;
  const label = points.map((p) => `${monthLabel(p.month)}: ${t.income} ${brl(p.income)}, ${t.home.spending} ${brl(p.spending)}`).join("; ");

  return (
    <div className="isb">
      <ul className="legend legend-inline">
        <li><i style={{ background: "var(--series-income)" }} aria-hidden="true" /><span>{t.income}</span></li>
        <li><i style={{ background: "var(--series-spend)" }} aria-hidden="true" /><span>{t.home.spending}</span></li>
      </ul>
      <div className="isb-plot" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} className="isb-svg" role="group" aria-label={t.home.trendTitle}>
          <title>{`${t.home.trendTitle}: ${label}`}</title>
          {points.map((p, i) => {
            const x0 = x(p.month) ?? 0;
            const dim = p.month !== current && hover !== i ? 0.5 : 1;
            return (
              <g key={p.month} opacity={dim}>
                {hover === i && <rect x={x0 - 4} y={0} width={x.bandwidth() + 8} height={H} rx={6} fill="var(--track)" opacity={0.5} />}
                <path d={barPath(x0, bw, y(Math.max(0, p.income)), H)} fill="var(--series-income)" />
                <path d={barPath(x0 + bw + GAP, bw, y(Math.max(0, p.spending)), H)} fill="var(--series-spend)" />
              </g>
            );
          })}
          <line x1={0} x2={W} y1={H - 0.5} y2={H - 0.5} stroke="var(--line)" />
          {points.map((p, i) => {
            const step = W / points.length;
            return (
              <rect
                key={`hit-${p.month}`}
                x={i * step}
                y={0}
                width={step}
                height={H}
                fill="transparent"
                tabIndex={0}
                role="img"
                aria-label={`${monthLabel(p.month)}: ${t.income} ${brl(p.income)}, ${t.home.spending} ${brl(p.spending)}`}
                className="isb-hit"
                onMouseEnter={() => setHover(i)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                onTouchStart={() => setHover(i)}
              />
            );
          })}
        </svg>
        {active && hover !== null && (
          <div
            className={`tooltip${hover === 0 ? " tip-start" : hover === points.length - 1 ? " tip-end" : ""}`}
            role="status"
            style={{ left: `${(((x(active.month) ?? 0) + x.bandwidth() / 2) / W) * 100}%` }}
          >
            <strong>{monthLabel(active.month)}</strong>
            <span><i style={{ background: "var(--series-income)" }} aria-hidden="true" />{t.income} {brlCompact(active.income)}</span>
            <span><i style={{ background: "var(--series-spend)" }} aria-hidden="true" />{t.home.spending} {brlCompact(active.spending)}</span>
          </div>
        )}
      </div>
      <div className="isb-x" aria-hidden="true">
        {points.map((p) => (
          <span key={p.month} className={p.month === current ? "on" : undefined}>{monthShort(p.month)}</span>
        ))}
      </div>
      <div className="sr-only">
<table>
        <caption>{t.home.chartTable}</caption>
        <thead>
          <tr><th scope="col">{t.home.month}</th><th scope="col">{t.income}</th><th scope="col">{t.home.spending}</th></tr>
        </thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.month}><th scope="row">{monthLabel(p.month)}</th><td>{brl(p.income)}</td><td>{brl(p.spending)}</td></tr>
          ))}
        </tbody>
      </table>
</div>
    </div>
  );
}
