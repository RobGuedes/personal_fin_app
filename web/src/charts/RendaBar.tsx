import type { components } from "../api/schema";
import { t } from "../i18n/pt-BR";
import { brl, pct } from "../lib/format";

export type RendaSplit = components["schemas"]["RendaSplitOut"];

interface Segment {
  key: string;
  label: string;
  value: number;
  color: string;
}

/**
 * One 100% bar of the month's income: Despesas, Outros, Sobrou.
 * Deficit: the bar is scaled to outflows, a marker shows where income ended and
 * the part past it is underlined as "Faltou". % are always of renda.
 */
export function RendaBar({ split }: { split: RendaSplit }) {
  const s = t.home.split;
  const segs: Segment[] = [
    { key: "despesas", label: s.despesas, value: split.despesas, color: "var(--split-despesas)" },
    { key: "outros", label: s.outros, value: split.outros, color: "var(--split-outros)" },
  ];
  if (!split.deficit) segs.push({ key: "sobrou", label: s.sobrou, value: split.sobrou, color: "var(--positive)" });
  const base = split.renda > 0 ? split.renda : split.scale || 1;
  const scale = split.scale || 1;
  const incomeAt = split.deficit ? (Math.max(split.renda, 0) / scale) * 100 : 100;
  const legend = [
    ...segs.map((g) => ({ ...g, text: `${g.label} ${pct(g.value / base)}` })),
    ...(split.deficit
      ? [{ key: "faltou", label: s.faltou, value: -split.sobrou, color: "var(--warning)", text: `${s.faltou} ${pct(-split.sobrou / base)}` }]
      : []),
  ];
  const summary = legend.map((g) => `${g.text} (${brl(g.value)})`).join(", ");

  return (
    <div className="renda-bar">
      <div className="renda-track" role="img" aria-label={summary}>
        <div className="renda-stack">
          {segs
            .filter((g) => g.value > 0)
            .map((g) => (
              <b key={g.key} style={{ flexGrow: g.value, background: g.color }} title={`${g.label}: ${brl(g.value)}`} />
            ))}
        </div>
        {split.deficit && (
          <>
            <span className="renda-marker" data-testid="income-marker" style={{ left: `${incomeAt}%` }} title={t.home.incomeEnd} />
            <span className="renda-short" style={{ left: `${incomeAt}%` }} />
          </>
        )}
      </div>
      <ul className="legend">
        {legend.map((g) => (
          <li key={g.key}>
            <i style={{ background: g.color }} aria-hidden="true" />
            <span>{g.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
