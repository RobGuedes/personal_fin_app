import type { SankeyFilter } from "../charts/Sankey";

/** `?mes=` value meaning "all months" (a link without `mes` opens on the current month). */
export const ALL_MONTHS = "todos";

/** Transações deep link for a node/category filter; without `month` (YYYY-MM, multi-month periods) it asks for all months. */
export function transacoesLink(filter: NonNullable<SankeyFilter>, opts: { month?: string } = {}): string {
  const p = new URLSearchParams();
  p.set("mes", opts.month || ALL_MONTHS);
  if (filter.category) p.set("categoria", filter.category);
  if (filter.line) p.set("linha", filter.line);
  return `/transacoes?${p.toString()}`;
}
