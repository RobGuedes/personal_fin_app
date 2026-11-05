import type { ReactNode } from "react";
import { useAccounts, useTaxonomy } from "../../api/queries";
import { t } from "../../i18n/pt-BR";
import { monthLabel, shiftMonth } from "../../lib/format";
import { orderLines } from "../../components/CategoryPicker";
import { UNCATEGORIZED } from "../../components/CategoryRow";

export { UNCATEGORIZED };

export interface TxFilters {
  month: string;
  account: string;
  category: string;
  line: string;
  method: string;
  unreviewed: boolean;
}
export const NO_FILTERS: TxFilters = { month: "", account: "", category: "", line: "", method: "", unreviewed: false };
const MONTHS_BACK = 13;

/** The list opens on the current month (as in the mockup); "Todos os meses" is a choice, not the default. */
export function defaultFilters(currentMonth: string): TxFilters {
  return { ...NO_FILTERS, month: currentMonth };
}

/** True when anything differs from the defaults (the default month is not an active filter). */
export function hasFilters(f: TxFilters, defaults: TxFilters): boolean {
  return (Object.keys(defaults) as (keyof TxFilters)[]).some((k) => f[k] !== defaults[k]);
}

/** A native select dressed as a chip: the selected option's text is the chip text, so it reads like the mockup. */
function SelectChip({ label, value, onChange, children }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  children: ReactNode;
}) {
  return (
    <span className={`fchip fchip-select${value ? " sel" : ""}`}>
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        {children}
      </select>
    </span>
  );
}

interface FiltersProps {
  value: TxFilters;
  onChange: (f: TxFilters) => void;
  /** YYYY-MM of today: the period list counts back from it. */
  currentMonth: string;
  /** What "Limpar filtros" returns to. */
  defaults: TxFilters;
}

export function Filters({ value, onChange, currentMonth, defaults }: FiltersProps) {
  const taxonomy = useTaxonomy();
  const accounts = (useAccounts().data ?? []).map((a) => a.label); // the API accepts the label
  const set = <K extends keyof TxFilters>(k: K, v: TxFilters[K]) => onChange({ ...value, [k]: v });
  const months = Array.from({ length: MONTHS_BACK }, (_, i) => shiftMonth(currentMonth, -i));
  // A deep-linked month older than the list (or after today's month) still needs its option.
  if (value.month && !months.includes(value.month)) months.push(value.month);
  const year = currentMonth.slice(0, 4);
  const lines = orderLines(taxonomy.data?.lines ?? [], "out");
  const cats = taxonomy.data?.categories ?? [];
  // Only lines rows can belong to: computed lines (tax provision, net income) have no categories.
  const matchable = lines.filter((l) => cats.some((c) => c.line === l.id));

  return (
    <div className="tx-filters" role="group" aria-label={t.tx.filters}>
      <SelectChip label={t.tx.period} value={value.month} onChange={(v) => set("month", v)}>
        <option value="">{t.tx.allMonths}</option>
        {months.map((m) => (
          <option key={m} value={m}>
            {monthLabel(m)}{m.slice(0, 4) !== year ? ` ${m.slice(0, 4)}` : ""}
          </option>
        ))}
      </SelectChip>
      <SelectChip label={t.tx.account} value={value.account} onChange={(v) => set("account", v)}>
        <option value="">{t.tx.allAccounts}</option>
        {[...new Set([...accounts, ...(value.account ? [value.account] : [])])].sort((a, b) => a.localeCompare(b, "pt-BR")).map((a) => (
          <option key={a} value={a}>{a}</option>
        ))}
      </SelectChip>
      <SelectChip label={t.tx.anyCategory} value={value.category} onChange={(v) => set("category", v)}>
        <option value="">{t.tx.anyCategory}</option>
        <option value={UNCATEGORIZED}>{t.tx.uncategorized}</option>
        {lines.map((l) => (
          <optgroup key={l.id} label={t.review.lines[l.id] ?? l.label}>
            {cats.filter((c) => c.line === l.id).map((c) => (
              <option key={c.id} value={c.id}>{c.label}</option>
            ))}
          </optgroup>
        ))}
      </SelectChip>
      <button
        type="button"
        className={`fchip${value.unreviewed ? " sel" : ""}`}
        aria-pressed={value.unreviewed}
        onClick={() => set("unreviewed", !value.unreviewed)}
      >
        {t.tx.unreviewed}
      </button>
      <SelectChip label={t.tx.anyLine} value={value.line} onChange={(v) => set("line", v)}>
        <option value="">{t.tx.anyLine}</option>
        {matchable.map((l) => (
          <option key={l.id} value={l.id}>{t.review.lines[l.id] ?? l.label}</option>
        ))}
      </SelectChip>
      <SelectChip label={t.tx.anyMethod} value={value.method} onChange={(v) => set("method", v)}>
        <option value="">{t.tx.anyMethod}</option>
        {Object.entries(t.review.methods).map(([id, label]) => (
          <option key={id} value={id}>{label}</option>
        ))}
      </SelectChip>
      {hasFilters(value, defaults) && (
        <button type="button" className="fchip fchip-clear" onClick={() => onChange(defaults)}>
          {t.tx.clear}
        </button>
      )}
    </div>
  );
}
