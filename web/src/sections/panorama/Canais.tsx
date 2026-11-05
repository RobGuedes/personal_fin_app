import { useState } from "react";
import type { ChannelsResponse } from "../../api/queries";
import { t } from "../../i18n/pt-BR";
import { brl, brlCompact, monthLabel, monthShort } from "../../lib/format";

const W = 320;
const H = 120;
const SLOTS = 7;
const colorOf = (i: number) => `var(--cat-${i % SLOTS})`;

/** Outflows per payment method: one stacked bar per month, a legend, hover/tap tooltip, and the full table. */
export function Canais({ data }: { data: ChannelsResponse }) {
  const [hover, setHover] = useState<number | null>(null);
  const { months, channels } = data;
  if (channels.length === 0 || months.length === 0) return <p className="empty">{t.panorama.empty}</p>;
  const totals = months.map((m) => data.totals[m] ?? 0); // from the API: the UI sums nothing
  const max = Math.max(1, ...totals);
  const step = W / months.length;
  const bw = step * 0.62;
  const alt = months.map((m, i) => `${monthLabel(m)}: ${brl(totals[i])}`).join("; ");

  return (
    <div className="canais">
      <ul className="legend legend-inline">
        {channels.map((c, i) => <li key={c.method}><i style={{ background: colorOf(i) }} aria-hidden="true" /><span>{c.label}</span></li>)}
      </ul>
      <div className="canais-plot" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} className="canais-svg" role="group" aria-label={t.panorama.channelsTitle}>
          <title>{`${t.panorama.channelsTitle}: ${alt}`}</title>
          {months.map((m, mi) => {
            let y = H;
            const x = mi * step + (step - bw) / 2;
            return (
              <g key={m} opacity={hover !== null && hover !== mi ? 0.55 : 1}>
                {channels.map((c, ci) => {
                  const h = ((c.values[m] ?? 0) / max) * (H - 6);
                  y -= h;
                  return h > 0 ? <rect key={c.method} x={x} y={y} width={bw} height={h} fill={colorOf(ci)} stroke="var(--card)" strokeWidth={0.5} /> : null;
                })}
                <rect x={mi * step} y={0} width={step} height={H} fill="transparent" tabIndex={0} role="img"
                      data-testid="canais-hit" aria-label={`${monthLabel(m)}: ${brl(totals[mi])}`} className="canais-hit"
                      onMouseEnter={() => setHover(mi)} onFocus={() => setHover(mi)} onBlur={() => setHover(null)}
                      onTouchStart={() => setHover(mi)} />
              </g>
            );
          })}
          <line x1={0} x2={W} y1={H - 0.5} y2={H - 0.5} stroke="var(--line)" />
        </svg>
        {hover !== null && (
          <div className={`tooltip${hover === 0 ? " tip-start" : hover === months.length - 1 ? " tip-end" : ""}`} role="status"
               style={{ left: `${((hover + 0.5) / months.length) * 100}%` }}>
            <strong>{monthLabel(months[hover])}</strong>
            {channels.map((c, ci) => (c.values[months[hover]] ?? 0) > 0 && (
              <span key={c.method}><i style={{ background: colorOf(ci) }} aria-hidden="true" />{c.label} {brlCompact(c.values[months[hover]])}</span>
            ))}
          </div>
        )}
      </div>
      <div className="isb-x" aria-hidden="true">{months.map((m) => <span key={m}>{monthShort(m)}</span>)}</div>
      <p className="note">{t.panorama.channelsNote}</p>
      <div className="pnl-scroll">
        <table className="pnl">
          <thead>
            <tr>
              <th scope="col">{t.panorama.line}</th>
              {months.map((m) => <th key={m} scope="col">{monthShort(m)}</th>)}
              <th scope="col">{t.panorama.total}</th>
            </tr>
          </thead>
          <tbody>
            {channels.map((c) => (
              <tr key={c.method}>
                <th scope="row"><span>{c.label}</span></th>
                {months.map((m) => <td key={m}>{brlCompact(c.values[m] ?? 0)}</td>)}
                <td className="tot">{brlCompact(c.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
