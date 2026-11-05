import { t } from "../i18n/pt-BR";

/** One part of a whole, already colored: a stacked-bar segment or a doughnut slice. */
export interface Slice {
  key: string;
  label: string;
  value: number;
  color: string;
  /** Text color for labels drawn on the slice. */
  ink: string;
}

/** Reserved key of the folded slice (never a category id). */
export const OTHER_KEY = "__other";

/**
 * Up to `keep + 1` slices are shown as they are; more keep the `keep` largest (input must be largest first) and
 * fold the rest into one gray slice (folding a single item into "Outras" would only hide its name).
 */
export function foldOther(items: Slice[], keep = 5, label: string = t.home.others): Slice[] {
  if (items.length <= keep + 1) return items;
  const rest = items.slice(keep).reduce((sum, s) => sum + s.value, 0);
  return [
    ...items.slice(0, keep),
    { key: OTHER_KEY, label, value: rest, color: "var(--cat-other)", ink: "var(--cat-other-ink)" },
  ];
}
