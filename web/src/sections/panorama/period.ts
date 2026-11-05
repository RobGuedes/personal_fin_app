/** URL value of `?periodo=`: a single month, the last 12 months, or the calendar year. */
export type PeriodKind = "mes" | "12m" | "ano";

export function parseKind(raw: string | null): PeriodKind {
  return raw === "mes" || raw === "ano" ? raw : "12m";
}

/** The `period` query value the API expects, or null while the server's current month (YYYY-MM) is still unknown.
 *  "Mês" = the server's current month, "Ano" = its year to date; the browser clock is never used. */
export function apiPeriod(kind: PeriodKind, currentMonth?: string): string | null {
  if (kind === "12m") return "last12";
  if (!currentMonth) return null;
  return kind === "mes" ? `month:${currentMonth}` : `year:${currentMonth.slice(0, 4)}`;
}

/** YYYY-MM when the period is a single month (links into Transações then carry `mes`), else undefined. */
export function singleMonth(kind: PeriodKind, currentMonth?: string): string | undefined {
  return kind === "mes" ? currentMonth : undefined;
}
