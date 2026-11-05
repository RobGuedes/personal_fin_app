const THOUSANDS = /^-?[1-9]\d{0,2}(\.\d{3})+$/; // "1.500", "1.234.567"; a leading 0 is a decimal ("0.500")
const INT_GROUPED = /^-?([1-9]\d{0,2}(\.\d{3})+|\d+)$/;

/**
 * Parses what a person types as a BRL amount: "1.234,56", "1234,56", "1500", "-20.5", "−300".
 * NaN when it is not a number or is ambiguous/malformed (en-US "1,234.56", misplaced dots with a comma).
 */
export function parseAmount(text: string): number {
  let s = text.trim().replace(/\s/g, "").replace(/^[−–]/, "-");
  if (s === "") return NaN;
  if (s.includes(",")) {
    const [int, frac, ...extra] = s.split(",");
    if (extra.length || !/^\d+$/.test(frac ?? "") || !INT_GROUPED.test(int)) return NaN;
    s = `${int.replace(/\./g, "")}.${frac}`;
  } else if (THOUSANDS.test(s)) s = s.replace(/\./g, ""); // "1.500" is fifteen hundred in pt-BR
  return /^-?\d+(\.\d+)?$/.test(s) ? Number(s) : NaN;
}
