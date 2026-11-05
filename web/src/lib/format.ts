const MINUS = "−";
const nf2 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const WEEKDAYS = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const MONTHS_SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const MONTHS = [
  "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
  "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
];

/** R$ 1.234,56; negatives as −R$ 12,00 (single U+2212, never a second sign). */
export function brl(v: number): string {
  const body = `R$ ${nf2.format(Math.abs(v))}`;
  return v < 0 && Math.round(Math.abs(v) * 100) > 0 ? MINUS + body : body;
}

function num(n: number, min: number, max: number): string {
  return new Intl.NumberFormat("pt-BR", { minimumFractionDigits: min, maximumFractionDigits: max }).format(n);
}

/** R$ 950 | R$ 54,9 mil | R$ 1,24 mi. Rounds first, then picks the unit; no minus for zero. */
export function brlCompact(v: number): string {
  const a = Math.abs(v);
  const r = Math.round(a);
  let body: string;
  if (Math.round(a / 10_000) >= 100) body = `R$ ${num(a / 1_000_000, 2, 2)} mi`; // >= 999.500 rounds to 1,00 mi
  else if (r >= 1_000) body = `R$ ${num(a / 1_000, 0, 1)} mil`;
  else body = `R$ ${num(r, 0, 0)}`;
  const zero = body === "R$ 0" || body === "R$ 0,0 mil";
  return v < 0 && !zero ? MINUS + body : body;
}

function parts(iso: string): [number, number, number] {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return [y, m, d];
}

const LOCAL_DAY = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/Sao_Paulo", year: "numeric", month: "2-digit", day: "2-digit",
}); // en-CA formats as YYYY-MM-DD

/** Calendar day of a value: a date-only "YYYY-MM-DD" as is; a timestamp in São Paulo time (not its UTC day). */
function localDay(iso: string): string {
  if (iso.length <= 10) return iso;
  const when = new Date(iso);
  return Number.isNaN(when.getTime()) ? iso.slice(0, 10) : LOCAL_DAY.format(when);
}

/** 2026-10-24 -> 24/10/2026; 2026-11-03T01:39:58Z -> 02/11/2026 (São Paulo day). */
export function dateBR(iso: string): string {
  const [y, m, d] = parts(localDay(iso));
  return `${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}/${y}`;
}

/** 2026-10-23 -> "sex, 23 out" */
export function dayLabel(iso: string): string {
  const [y, m, d] = parts(iso);
  const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return `${WEEKDAYS[wd]}, ${d} ${MONTHS_SHORT[m - 1]}`;
}

/** 2026-10 -> "Outubro" */
export function monthLabel(ym: string): string {
  return MONTHS[Number(ym.slice(5, 7)) - 1];
}

/** 0.384 -> "38%" */
export function pct(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

const nf0 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });

/** R$ 20.600 — whole reais for headline numbers and category amounts. */
export function brlInt(v: number): string {
  const r = Math.round(Math.abs(v));
  const body = `R$ ${nf0.format(r)}`;
  return v < 0 && r > 0 ? MINUS + body : body;
}

/** 2026-10 -> 2026-09 (delta months). */
export function shiftMonth(ym: string, delta: number): string {
  const i = Number(ym.slice(0, 4)) * 12 + Number(ym.slice(5, 7)) - 1 + delta;
  return `${Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, "0")}`;
}

/** 2026-10 -> "out" */
export function monthShort(ym: string): string {
  return MONTHS_SHORT[Number(ym.slice(5, 7)) - 1];
}

/** Day header for transaction lists: "HOJE · SÁB 24", "SEX 23"; other months add the month, other years the year. */
export function dayHeader(iso: string, today: string): string {
  const [y, m, d] = parts(iso);
  const [ty, tm] = parts(today);
  const wd = WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()].toUpperCase();
  if (iso.slice(0, 10) === today.slice(0, 10)) return `HOJE · ${wd} ${d}`;
  let label = `${wd} ${d}`;
  if (y !== ty || m !== tm) label += ` ${MONTHS_SHORT[m - 1].toUpperCase()}`;
  if (y !== ty) label += ` ${y}`;
  return label;
}

function sign(v: number): string {
  const cents = Math.round(v * 100);
  return cents > 0 ? "+ " : cents < 0 ? `${MINUS} ` : "";
}

/** +28,4k | −6,2k | 0 (bar labels: thousands of R$, one decimal; no sign when it rounds to zero). */
export function brlK(v: number): string {
  const k = Math.round(Math.abs(v) / 100) / 10;
  if (k === 0) return "0";
  return `${v < 0 ? MINUS : "+"}${num(k, 1, 1)}k`;
}

/** + R$ 8.490,10 | − R$ 312,40 | R$ 0,00 (day totals). */
export function brlSigned(v: number): string {
  return `${sign(v)}R$ ${nf2.format(Math.abs(v))}`;
}

/** + 9.810,00 | − 218,90 (list rows); `signed = false` drops the sign (excluded rows). */
export function amountSigned(v: number, signed = true): string {
  return `${signed ? sign(v) : ""}${nf2.format(Math.abs(v))}`;
}

/** Local calendar date as YYYY-MM-DD. */
export function todayISO(now = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

/** 0.112 -> "11,2%" (one decimal; for shares compared with a target). */
export function pct1(fraction: number): string {
  return `${num(fraction * 100, 1, 1)}%`;
}
