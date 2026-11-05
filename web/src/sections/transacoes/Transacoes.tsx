import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router";
import { api } from "../../api/client";
import { useCurrentMonth, useTaxonomy } from "../../api/queries";
import type { components } from "../../api/schema";
import type { Direction } from "../../components/CategoryPicker";
import { Skeleton } from "../../components/Skeleton";
import { t } from "../../i18n/pt-BR";
import { brlSigned, dayHeader, todayISO } from "../../lib/format";
import { ALL_MONTHS } from "../../lib/links";
import { defaultFilters, Filters, hasFilters, UNCATEGORIZED, type TxFilters } from "./Filters";
import { TxRow, type TxOut } from "./TxRow";
import { TxSheet } from "./TxSheet";
import "./transacoes.css";

type TxPage = components["schemas"]["TxPage"];

const PAGE = 100;
const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;
const LINE_RE = /^[a-z_]+$/;
const CATEGORY_RE = /^[a-z0-9_]+$/;

/** Deep links: `?mes=YYYY-MM|todos&linha=<line id>&categoria=<leaf id>` preset the first filters; the rest are defaults.
 *  `mes=todos` = all months; no `mes` = the current month (plain navigation). */
function filtersFromUrl(search: string, defaults: TxFilters): TxFilters {
  const p = new URLSearchParams(search);
  const mes = p.get("mes");
  const linha = p.get("linha");
  const categoria = p.get("categoria");
  return {
    ...defaults,
    ...(mes === ALL_MONTHS ? { month: "" } : mes && MONTH_RE.test(mes) ? { month: mes } : {}),
    ...(linha && LINE_RE.test(linha) ? { line: linha } : {}),
    ...(categoria && CATEGORY_RE.test(categoria) ? { category: categoria } : {}),
  };
}
const DEBOUNCE_MS = 250;
const CHIPS = 6;
/** Lines whose categories pad the sheet's chips when the loaded list has few of a direction. */
const PAD_LINE: Record<Direction, string> = { in: "income", out: "expenses" };

function params(q: string, f: TxFilters, cursor: string | null): string {
  const p = new URLSearchParams();
  if (q) p.set("q", q);
  if (f.month) p.set("month", f.month);
  if (f.account) p.set("account", f.account);
  if (f.category) p.set("category", f.category);
  if (f.line) p.set("line", f.line);
  if (f.method) p.set("method", f.method);
  if (f.unreviewed) p.set("unreviewed", "true");
  if (cursor) p.set("cursor", cursor);
  p.set("limit", String(PAGE));
  return p.toString();
}

interface Day {
  date: string;
  total: number; // non-excluded rows only
  items: TxOut[];
}

/** Rows arrive date-desc; consecutive dates form a day. Excluded rows are listed but never counted. */
function groupByDay(items: TxOut[]): Day[] {
  const days: Day[] = [];
  for (const tx of items) {
    const date = tx.date.slice(0, 10);
    let day = days[days.length - 1];
    if (!day || day.date !== date) {
      day = { date, total: 0, items: [] };
      days.push(day);
    }
    day.items.push(tx);
    if (!tx.excluded) day.total += tx.amount;
  }
  for (const d of days) d.total = Math.round(d.total * 100) / 100;
  return days;
}

/** "Today" is the server's (America/Sao_Paulo), as on Início: the machine clock may be off or in another zone.
 *  Only if the server cannot answer does the list fall back to the browser's day. */
export function Transacoes() {
  const current = useCurrentMonth();
  if (current.isPending) return <div className="tx-page" aria-busy="true"><p className="empty">{t.loading}</p></div>;
  const today = current.data ? `${current.data.month}-${String(current.data.day).padStart(2, "0")}` : todayISO();
  return <TransacoesView today={today} />;
}

function TransacoesView({ today }: { today: string }) {
  const taxonomy = useTaxonomy();
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const currentMonth = today.slice(0, 7);
  const defaults = useMemo(() => defaultFilters(currentMonth), [currentMonth]);
  // useLocation rather than useSearchParams: see Inicio (the latter trips the no-external-URL build check).
  const location = useLocation();
  const [filters, setFilters] = useState<TxFilters>(() => filtersFromUrl(location.search, defaults));
  const [openId, setOpenId] = useState<string | null>(null);
  const originId = useRef<string | null>(null); // the row that opened the sheet gets focus back
  const sentinel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const h = window.setTimeout(() => setQ(text.trim()), DEBOUNCE_MS);
    return () => window.clearTimeout(h);
  }, [text]);

  const list = useInfiniteQuery({
    queryKey: ["transactions", "list", q, filters],
    queryFn: ({ pageParam }) => api<TxPage>(`/transactions?${params(q, filters, pageParam)}`),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
  });

  const items = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data]);
  const days = useMemo(() => groupByDay(items), [items]);
  const byId = useMemo(() => new Map(taxonomy.data?.categories.map((c) => [c.id, c]) ?? []), [taxonomy.data]);

  // Sheet chips: the categories used most in the loaded rows of that direction, padded from the direction's line.
  const topFor = useCallback(
    (direction: Direction) => {
      const counts = new Map<string, number>();
      for (const tx of items) {
        if (tx.category_id === UNCATEGORIZED || (tx.amount > 0) !== (direction === "in")) continue;
        counts.set(tx.category_id, (counts.get(tx.category_id) ?? 0) + 1);
      }
      const ids = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([id]) => id);
      for (const c of taxonomy.data?.categories ?? []) if (c.line === PAD_LINE[direction] && !ids.includes(c.id)) ids.push(c.id);
      return ids.filter((id) => byId.has(id)).slice(0, CHIPS);
    },
    [items, taxonomy.data, byId],
  );

  // Infinite scroll; the "Carregar mais" button stays as the fallback (and for keyboard users).
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = list;
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !hasNextPage || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting) && !isFetchingNextPage) void fetchNextPage();
      },
      { rootMargin: "600px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const open = useCallback((id: string) => {
    originId.current ??= id;
    setOpenId(id);
  }, []);
  const returnTo = useRef<string | null>(null);
  const close = useCallback(() => {
    returnTo.current = originId.current;
    originId.current = null;
    setOpenId(null);
  }, []);
  // After the sheet unmounts, focus goes back to the row that opened it.
  useEffect(() => {
    if (openId !== null || !returnTo.current) return;
    const id = returnTo.current;
    returnTo.current = null;
    document.querySelector<HTMLElement>(`[data-tx-id="${CSS.escape(id)}"]`)?.focus();
  }, [openId]);

  const clearAll = () => {
    setText("");
    setQ("");
    setFilters(defaults);
  };

  return (
    <div className="tx-page">
      <h1>{t.tx.title}</h1>
      <div className="tx-search">
        <span className="tx-search-icon" aria-hidden="true">🔍</span>
        <input
          type="search"
          data-search
          className="tx-search-input"
          placeholder={t.tx.searchPlaceholder}
          aria-label={t.tx.searchLabel}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape" && text) {
              e.preventDefault();
              setText("");
            }
          }}
        />
        <kbd className="tx-kbd" aria-hidden="true">/</kbd>
      </div>
      <Filters value={filters} onChange={setFilters} currentMonth={currentMonth} defaults={defaults} />

      {list.isPending && (
        <div aria-busy="true">
          <Skeleton height={120} />
          <Skeleton height={180} />
        </div>
      )}
      {list.isError && !list.data && (
        <div className="card empty">
          {list.error instanceof Error ? list.error.message : t.genericError}
        </div>
      )}
      {list.data && items.length === 0 && (
        <div className="card empty tx-empty">
          <strong>{t.tx.empty}</strong>
          <p>{t.tx.emptyHint}</p>
          {(q || hasFilters(filters, defaults)) && (
            <button type="button" className="fchip" onClick={clearAll}>{t.tx.clear}</button>
          )}
        </div>
      )}

      <div className={`tx-days${list.isPlaceholderData ? " is-stale" : ""}`}>
        {days.map((day, i) => {
          // The day at the page boundary may continue on the next page: no partial figure until it loads.
          const partial = hasNextPage && i === days.length - 1;
          return (
          <section key={day.date} className="tx-day" aria-label={dayHeader(day.date, today)}>
            <h2 className="tx-day-head">
              <span>{dayHeader(day.date, today)}</span>
              {partial ? (
                <span className="tx-day-total" aria-label={t.tx.dayTotalPending}>…</span>
              ) : (
                <span className={`tx-day-total${day.total > 0 ? " is-in" : ""}`}>
                  <span className="sr-only">{t.tx.dayTotal}: </span>
                  {brlSigned(day.total)}
                </span>
              )}
            </h2>
            <div className="card tx-group">
              {day.items.map((tx) => (
                <TxRow key={tx.id} tx={tx} category={byId.get(tx.category_id)} onOpen={open} />
              ))}
            </div>
          </section>
          );
        })}
      </div>

      <div ref={sentinel} className="tx-sentinel" />
      {hasNextPage && (
        <button type="button" className="fchip tx-more" disabled={isFetchingNextPage} onClick={() => void fetchNextPage()}>
          {isFetchingNextPage ? t.tx.loadingMore : t.tx.loadMore}
        </button>
      )}
      {list.data && items.length > 0 && !hasNextPage && <p className="tx-end">{t.tx.end}</p>}

      {openId && <TxSheet id={openId} onClose={close} onOpen={open} topFor={topFor} />}
    </div>
  );
}
