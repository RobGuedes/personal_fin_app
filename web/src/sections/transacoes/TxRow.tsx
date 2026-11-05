import type { components } from "../../api/schema";
import { categoryColor, type Category } from "../../components/CategoryRow";
import { t } from "../../i18n/pt-BR";
import { amountSigned } from "../../lib/format";

export type TxOut = components["schemas"]["TxOut"];

export const txName = (tx: Pick<TxOut, "counterparty" | "description">) => tx.counterparty || tx.description;
export const txCategoryText = (tx: Pick<TxOut, "category_label">) => tx.category_label ?? t.tx.uncategorized;

export function TxIcon({ category, size = "md" }: { category?: Category; size?: "md" | "lg" }) {
  const color = categoryColor(category);
  return (
    <span
      className={`tx-dot tx-dot-${size}`}
      style={{ background: `color-mix(in srgb, ${color} 18%, var(--card))` }}
      aria-hidden="true"
    >
      {category?.icon ?? "❔"}
    </span>
  );
}

interface TxRowProps {
  tx: TxOut;
  category?: Category;
  onOpen: (id: string) => void;
}

/** One list row: icon, name (+ installment badge), "category · account", amount (inflows green). Excluded rows are
 *  dimmed, keep their label and show the amount without a sign: they never count in the totals. */
export function TxRow({ tx, category, onOpen }: TxRowProps) {
  const inflow = tx.amount > 0;
  const cls = ["tx-row", tx.excluded ? "is-excluded" : "", inflow && !tx.excluded ? "is-in" : ""].filter(Boolean).join(" ");
  return (
    <button type="button" className={cls} data-tx-id={tx.id} onClick={() => onOpen(tx.id)}>
      <TxIcon category={category} />
      <span className="tx-mid">
        <span className="tx-name">
          <span className="tx-name-text">{txName(tx)}</span>
          {tx.installment && <span className="tx-badge">{tx.installment}</span>}
        </span>
        <span className="tx-sub">
          {tx.in_review && <span className="tx-review" title={t.tx.toReview}><i aria-hidden="true" />{t.tx.toReview} · </span>}
          {txCategoryText(tx)} · {tx.account}
          {tx.note && <span className="tx-note"> · {tx.note}</span>}
        </span>
      </span>
      <span className="tx-amount">
        {tx.excluded && <span className="sr-only">{t.tx.notCounted}: </span>}
        {amountSigned(tx.amount, !tx.excluded)}
      </span>
    </button>
  );
}
