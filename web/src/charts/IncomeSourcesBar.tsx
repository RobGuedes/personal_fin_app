import { t } from "../i18n/pt-BR";
import { brl, brlCompact, pct } from "../lib/format";
import type { Slice } from "./slices";

/**
 * Where the month's income came from: one 100% bar (same look as RendaBar) and a legend
 * "Nome 65% · R$ 45,7 mil". `slices` are positive, largest first, already folded. `manual`: the month has manual
 * income entries, which the card's Transações link cannot list (they are not ledger rows), so a note says so.
 */
export function IncomeSourcesBar({ slices, manual = false }: { slices: Slice[]; manual?: boolean }) {
  const total = slices.reduce((sum, s) => sum + s.value, 0);
  if (total <= 0) return null;
  const share = (v: number) => pct(v / total);
  const summary = `${t.home.whereIncomeFrom}: ${slices.map((s) => `${s.label} ${share(s.value)} (${brl(s.value)})`).join(", ")}`;

  return (
    <div className="renda-bar income-bar">
      <div className="renda-track" role="img" aria-label={summary}>
        <div className="renda-stack">
          {slices.map((s) => (
            <b key={s.key} data-testid="income-segment" style={{ flexGrow: s.value, background: s.color }} />
          ))}
        </div>
      </div>
      <ul className="legend legend-inline income-legend">
        {slices.map((s) => (
          <li key={s.key}>
            <i style={{ background: s.color }} aria-hidden="true" />
            <span className="lg-name">{s.label}</span>{" "}
            <span className="lg-val">{`${share(s.value)} · ${brlCompact(s.value)}`}</span>
          </li>
        ))}
      </ul>
      {manual && <p className="income-note">{t.home.manualNote}</p>}
    </div>
  );
}
