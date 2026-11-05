import type { components } from "../api/schema";
import { t } from "../i18n/pt-BR";
import { brl, brlInt } from "../lib/format";

export type CategoryStatus = components["schemas"]["CategoryStatusOut"];
export type Category = components["schemas"]["CategoryOut"];

/** Color slots in tokens.css (--cat-0..7); the server assigns 0..N_SLOTS-1. */
const N_SLOTS = 8;

export function categoryColor(category?: Pick<Category, "color_slot"> | null): string {
  const slot = category?.color_slot;
  return slot === null || slot === undefined ? "var(--cat-other)" : `var(--cat-${slot % N_SLOTS})`;
}

/** Text color for labels drawn on top of `categoryColor` (contrast-picked per slot in tokens.css). */
export function categoryInk(category?: Pick<Category, "color_slot"> | null): string {
  const slot = category?.color_slot;
  return slot === null || slot === undefined ? "var(--cat-other-ink)" : `var(--cat-${slot % N_SLOTS}-ink)`;
}

export const UNCATEGORIZED = "uncategorized";

/** Display name of a category id: the taxonomy label, "Sem categoria" for uncategorized (it is not in /taxonomy). */
export function categoryName(id: string, category?: Pick<Category, "label"> | null): string {
  if (category) return category.label;
  return id === UNCATEGORIZED ? t.tx.uncategorized : id;
}

export function categoryIcon(id: string, category?: Pick<Category, "icon"> | null): string {
  return category?.icon ?? (id === UNCATEGORIZED ? "❔" : "•");
}

/** Amount, a bar to spent / max(spent, reference_month), a tick at reference_to_date, a note only when unusual. */
export function CategoryRow({ status, category }: { status: CategoryStatus; category?: Category }) {
  const color = categoryColor(category);
  const label = categoryName(status.category_id, category);
  const ref = status.reference_month ?? 0;
  const full = Math.max(status.spent, ref) || 1;
  const width = (status.spent / full) * 100;
  const tick = status.reference_to_date !== null ? Math.min(100, (status.reference_to_date / full) * 100) : null;
  const budget = status.reference_kind === "budget";
  const tip = [
    `${label}: ${brl(status.spent)}`,
    status.reference_to_date !== null ? `${budget ? t.home.budgetToDate : t.home.usualToDate}: ${brl(status.reference_to_date)}` : null,
    status.reference_month !== null ? `${budget ? t.home.budgetMonth : t.home.usualMonth}: ${brl(status.reference_month)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const over = status.pct_over !== null ? `+${Math.round(status.pct_over * 100)}%` : null;

  return (
    <li className="cat-row" data-testid="category-row">
      <div className="cat-head">
        <span className="cat-name">
          <span className="cat-dot" style={{ background: `color-mix(in srgb, ${color} 18%, var(--card))` }} aria-hidden="true">
            {categoryIcon(status.category_id, category)}
          </span>
          {label}
        </span>
        <strong className="cat-amount">{brlInt(status.spent)}</strong>
      </div>
      {/* One accessible name (aria-label); the hover tip is CSS generated content from data-tip, not a title. */}
      <div className="cat-bar" role="img" aria-label={tip} data-tip={tip}>
        <b style={{ width: `${width}%`, background: color }} />
        {tick !== null && <u style={{ left: `calc(${tick}% - 1px)` }} />}
      </div>
      {status.unusual && (over || status.note) && (
        <div className="cat-note">
          {over && <span className="hot">{over}</span>}
          {over && status.note && " · "}
          {status.note}
        </div>
      )}
    </li>
  );
}
