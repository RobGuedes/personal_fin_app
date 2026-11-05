import type { CounterpartiesResponse } from "../../api/queries";
import { t } from "../../i18n/pt-BR";
import { brl } from "../../lib/format";

/** Top counterparties by amount received in the period. */
export function QuemRecebe({ data }: { data: CounterpartiesResponse }) {
  if (data.counterparties.length === 0) return <p className="empty">{t.panorama.empty}</p>;
  return (
    <ol className="cp-list" aria-label={t.panorama.counterpartiesTitle}>
      {data.counterparties.map((c) => (
        <li key={c.name}>
          <span className="cp-name">{c.name}<small>{t.panorama.transactionsCount(c.count)}</small></span>
          <b>{brl(c.total)}</b>
        </li>
      ))}
    </ol>
  );
}
