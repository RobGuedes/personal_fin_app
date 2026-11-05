import { useEffect, useRef, useState, type PointerEvent } from "react";
import { t } from "../i18n/pt-BR";
import { brl, brlK, monthLabel, monthShort } from "../lib/format";

export interface ContributionPoint { month: string; value: number }

const MIN_BAR = 2; // px: a non-zero month never disappears

/**
 * Diverging bars from a zero baseline: net invested goes up (--div-pos), net withdrawn goes down (--div-neg).
 * Every bar carries an R$ k label; tooltip with the exact value on hover, tap or focus. Bars are soft except the
 * current (server) month and the hovered one, like Início › Renda e gastos.
 */
export function ContributionBars({ points, current }: { points: ContributionPoint[]; current?: string }) {
  const [active, setActive] = useState<number | null>(null);
  // Touch/pen browsers emit an emulated mouseenter after the tap: remember the last pointer type.
  const pointer = useRef<string | null>(null);
  const touchy = () => pointer.current === "touch" || pointer.current === "pen";

  useEffect(() => {
    if (active === null) return;
    const away = (e: Event) => {
      if (!(e.target as Element | null)?.closest?.(".cbars-plot")) setActive(null);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [active]);

  const up = Math.max(0, ...points.map((p) => p.value));
  const down = Math.max(0, ...points.map((p) => -p.value));
  const span = up + down || 1;
  const zero = (up / span) * 100; // baseline, % from the top of the plot
  const a = active !== null ? points[active] : null;
  const n = points.length;

  return (
    <div className="cbars">
      <ul className="legend legend-inline">
        <li><i style={{ background: "var(--div-pos)" }} aria-hidden="true" /><span>{t.wealth.invested}</span></li>
        <li><i style={{ background: "var(--div-neg)" }} aria-hidden="true" /><span>{t.wealth.withdrawn}</span></li>
      </ul>
      <div className="cbars-plot" data-testid="contrib-chart" role="group" aria-label={t.wealth.contributionsChart} onMouseLeave={() => setActive(null)}>
        <div className="cbars-area">
          <div className="cbars-zero" style={{ top: `${zero}%` }} aria-hidden="true" />
          {points.map((p, i) => {
            const label = brlK(p.value);
            const flat = label === "0";
            const h = (Math.abs(p.value) / span) * 100;
            const neg = p.value < 0 && !flat;
            const bar = flat
              ? null
              : neg
                ? { top: `${zero}%`, height: `max(${MIN_BAR}px, ${h}%)` }
                : { bottom: `${100 - zero}%`, height: `max(${MIN_BAR}px, ${h}%)` };
            return (
              <div
                key={p.month}
                className={`cbars-col${p.month === current ? " on" : ""}${active === i ? " hover" : ""}`}
                data-testid="contrib-hit"
                tabIndex={0}
                role="img"
                aria-label={`${monthLabel(p.month)}: ${brl(p.value)}`}
                onPointerEnter={(e: PointerEvent) => { pointer.current = e.pointerType; }}
                onPointerDown={(e: PointerEvent) => {
                  pointer.current = e.pointerType;
                  if (touchy()) setActive((cur) => (cur === i ? null : i));
                }}
                onMouseEnter={() => { if (!touchy()) setActive(i); }}
                onFocus={() => setActive(i)}
                onBlur={() => setActive(null)}
              >
                {bar && <i className={neg ? "is-neg" : undefined} style={bar} aria-hidden="true" />}
                <span
                  className={`cbars-val${neg ? " below" : ""}${flat ? " flat" : ""}`}
                  style={neg ? { top: `calc(${zero}% + max(${MIN_BAR}px, ${h}%) + 2px)` } : { bottom: `calc(${100 - zero}% + ${flat ? "0px" : `max(${MIN_BAR}px, ${h}%)`} + 2px)` }}
                  aria-hidden="true"
                >
                  {label}
                </span>
              </div>
            );
          })}
        </div>
        {a && active !== null && (
          <div
            className={`tooltip${active === 0 ? " tip-start" : active === n - 1 ? " tip-end" : ""}`}
            role="status"
            style={{ left: `${((active + 0.5) / n) * 100}%` }}
          >
            <strong>{monthLabel(a.month)}</strong>
            <span>{a.value < 0 ? t.wealth.withdrawn : t.wealth.invested} {brl(a.value)}</span>
          </div>
        )}
      </div>
      <div className="cbars-x" aria-hidden="true">
        {points.map((p) => <span key={p.month} className={p.month === current ? "on" : undefined}>{monthShort(p.month)}</span>)}
      </div>
      <div className="sr-only">
        <table>
          <caption>{t.wealth.contributionsChart}</caption>
          <thead><tr><th scope="col">{t.wealth.month}</th><th scope="col">{t.wealth.contributionsNote}</th></tr></thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.month}><th scope="row">{monthLabel(p.month)}</th><td>{brl(p.value)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
