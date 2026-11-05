import { arc, pie, type PieArcDatum } from "d3-shape";
import { useState } from "react";
import { t } from "../i18n/pt-BR";
import { brl, brlCompact, pct } from "../lib/format";
import type { Slice } from "./slices";

const SIZE = 136;
const R = SIZE / 2;
const INNER = 45;
const GAP = 2; // px of card surface between slices
const LABEL_MIN = 0.08; // % label on slices at least this share

/**
 * Month spending by category as a doughnut: `slices` largest first, already folded (top 5 + Outras).
 * d3-shape does the geometry only; the SVG is hand-written. Total in the hole, % on slices >= 8%,
 * legend (name + %) beside the ring on wide cards and below it on narrow ones (container query).
 */
export function SpendingDonut({ slices }: { slices: Slice[] }) {
  const [active, setActive] = useState<string | null>(null);
  const total = slices.reduce((sum, s) => sum + s.value, 0);
  if (total <= 0) return null;
  const share = (v: number) => v / total;
  const arcs = pie<Slice>()
    .value((s) => s.value)
    .sort(null)
    .padAngle(slices.length > 1 ? GAP / R : 0)(slices);
  const path = arc<PieArcDatum<Slice>>().innerRadius(INNER).outerRadius(R - 1).padRadius(R).cornerRadius(3);
  const mid = arc<PieArcDatum<Slice>>().innerRadius(INNER).outerRadius(R - 1);
  const shown = arcs.find((a) => a.data.key === active) ?? null;
  const describe = (s: Slice) => `${s.label}: ${brl(s.value)} (${pct(share(s.value))})`;
  const summary = `${t.home.byCategory}: ${slices.map(describe).join(", ")}`;
  const at = shown ? mid.centroid(shown) : null;

  return (
    <div className="donut">
      <div className="donut-body">
        <div className="donut-plot" onMouseLeave={() => setActive(null)}>
          <svg viewBox={`${-R} ${-R} ${SIZE} ${SIZE}`} className="donut-svg" role="group" aria-label={summary}>
            {arcs.map((a) => {
              const s = a.data;
              const [x, y] = mid.centroid(a);
              const dim = active !== null && active !== s.key;
              return (
                <g key={s.key} className={`donut-slice-g${dim ? " is-dim" : ""}`}>
                  <path
                    d={path(a) ?? ""}
                    fill={s.color}
                    className="donut-slice"
                    data-testid="donut-slice"
                    tabIndex={0}
                    role="img"
                    aria-label={describe(s)}
                    onMouseEnter={() => setActive(s.key)}
                    onFocus={() => setActive(s.key)}
                    onBlur={() => setActive(null)}
                    // Tap: focus already selected the slice, so click must not toggle it off; tapping elsewhere blurs.
                    onClick={() => setActive(s.key)}
                  />
                  {share(s.value) >= LABEL_MIN && (
                    <text x={x} y={y} className="donut-pct" fill={s.ink} aria-hidden="true">
                      {pct(share(s.value))}
                    </text>
                  )}
                </g>
              );
            })}
            <g aria-hidden="true" className="donut-center">
              <text y={-2} className="donut-total" data-testid="donut-total">{brlCompact(total)}</text>
              <text y={14} className="donut-word">{t.home.spentWord}</text>
            </g>
          </svg>
          {shown && at && (
            // No live region: the focused slice's aria-label already says the same thing.
            <div
              className={`tooltip donut-tip${at[0] < -R / 3 ? " tip-start" : at[0] > R / 3 ? " tip-end" : ""}`}
              aria-hidden="true"
              data-testid="donut-tip"
              style={{ left: `${((at[0] + R) / SIZE) * 100}%`, top: `${((at[1] + R) / SIZE) * 100}%` }}
            >
              <strong>{shown.data.label}</strong>
              <span>
                <i style={{ background: shown.data.color }} aria-hidden="true" />
                {brl(shown.data.value)} · {pct(share(shown.data.value))}
              </span>
            </div>
          )}
        </div>
        <ul className="donut-legend">
          {slices.map((s) => (
            <li key={s.key} className={active !== null && active !== s.key ? "is-dim" : undefined}>
              <i style={{ background: s.color }} aria-hidden="true" />
              <span className="lg-name">{s.label}</span>{" "}
              <span className="lg-val">{pct(share(s.value))}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
