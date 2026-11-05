import { useEffect, useRef, useState, type PointerEvent } from "react";
import { t } from "../i18n/pt-BR";
import { brl, brlCompact, dateBR } from "../lib/format";

export interface AreaPoint { date: string; value: number }

const W = 320;
const H = 110;
const PAD_T = 8;
const PAD_B = 4;

const day = (iso: string) => Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / 86_400_000;

/** Single-series area chart over dated points (x proportional to the date). Tooltip per day: hover or tap. */
export function AreaChart({ points, label }: { points: AreaPoint[]; label: string }) {
  const [active, setActive] = useState<number | null>(null);
  // Touch/pen browsers emit an emulated mouseenter after the tap: remember the last pointer type.
  const pointer = useRef<string | null>(null);
  const touchy = () => pointer.current === "touch" || pointer.current === "pen";

  useEffect(() => {
    if (active === null) return;
    const away = (e: Event) => {
      if (!(e.target as Element | null)?.closest?.(".area-plot")) setActive(null);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [active]);

  const d0 = day(points[0].date);
  const span = Math.max(1, day(points[points.length - 1].date) - d0);
  const vals = points.map((p) => p.value);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const range = hi - lo || Math.max(1, Math.abs(hi));
  const xs = points.map((p) => ((day(p.date) - d0) / span) * W);
  const ys = points.map((p) => PAD_T + (1 - (p.value - lo) / range) * (H - PAD_T - PAD_B));
  const line = points.map((_, i) => `${i === 0 ? "M" : "L"}${xs[i].toFixed(1)},${ys[i].toFixed(1)}`).join("");
  const area = `${line}L${W},${H}L0,${H}Z`;
  const summary = `${label}: ${dateBR(points[0].date)} ${brl(points[0].value)}, ${dateBR(points[points.length - 1].date)} ${brl(points[points.length - 1].value)}`;
  const a = active !== null ? points[active] : null;

  return (
    <div className="area-plot" data-testid="area-chart" onMouseLeave={() => setActive(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="area-svg" role="group" aria-label={label}>
        <title>{summary}</title>
        <defs>
          <linearGradient id="area-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="var(--accent)" stopOpacity="0.25" />
            <stop offset="1" stopColor="var(--accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#area-fill)" />
        <path d={line} fill="none" stroke="var(--accent)" strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        {a && active !== null && (
          <>
            <line x1={xs[active]} x2={xs[active]} y1={0} y2={H} stroke="var(--line)" />
            <circle cx={xs[active]} cy={ys[active]} r={4} fill="var(--accent)" stroke="var(--card)" strokeWidth={2} />
          </>
        )}
        {points.map((p, i) => {
          const left = i === 0 ? 0 : (xs[i - 1] + xs[i]) / 2;
          const right = i === points.length - 1 ? W : (xs[i] + xs[i + 1]) / 2;
          return (
            <rect
              key={p.date}
              data-testid="area-hit"
              x={left}
              y={0}
              width={Math.max(1, right - left)}
              height={H}
              fill="transparent"
              tabIndex={0}
              role="img"
              aria-label={`${dateBR(p.date)}: ${brl(p.value)}`}
              onPointerEnter={(e: PointerEvent) => { pointer.current = e.pointerType; }}
              onPointerDown={(e: PointerEvent) => {
                pointer.current = e.pointerType;
                if (touchy()) setActive((cur) => (cur === i ? null : i));
              }}
              onMouseEnter={() => { if (!touchy()) setActive(i); }}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
            />
          );
        })}
      </svg>
      {a && active !== null && (
        <div className="tooltip" role="status" style={{ left: `${Math.min(88, Math.max(12, (xs[active] / W) * 100))}%` }}>
          <strong>{dateBR(a.date)}</strong>
          <span>{brl(a.value)}</span>
        </div>
      )}
      <div className="area-axis" aria-hidden="true">
        <span>{dateBR(points[0].date)}</span>
        <span>{brlCompact(lo)} – {brlCompact(hi)}</span>
        <span>{dateBR(points[points.length - 1].date)}</span>
      </div>
      <div className="sr-only">
<table>
        <caption>{t.wealth.chartTable}</caption>
        <thead><tr><th scope="col">{t.wealth.date}</th><th scope="col">{t.wealth.netWorth}</th></tr></thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.date}><th scope="row">{dateBR(p.date)}</th><td>{brl(p.value)}</td></tr>
          ))}
        </tbody>
      </table>
</div>
    </div>
  );
}
