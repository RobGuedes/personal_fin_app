import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useCallback, useState, useSyncExternalStore } from "react";
import { useLocation, useNavigate } from "react-router";
import { api } from "../../api/client";
import { useSankey, useTaxonomy, type Taxonomy } from "../../api/queries";
import type { components } from "../../api/schema";
import { IncomeSpendBars, type TrendPoint } from "../../charts/IncomeSpendBars";
import { IncomeSourcesBar } from "../../charts/IncomeSourcesBar";
import { RendaBar } from "../../charts/RendaBar";
import { foldOther, type Slice } from "../../charts/slices";
import { Sankey } from "../../charts/Sankey";
import { SpendingDonut } from "../../charts/SpendingDonut";
import { Card } from "../../components/Card";
import { categoryColor, categoryInk, categoryName, CategoryRow } from "../../components/CategoryRow";
import { Skeleton } from "../../components/Skeleton";
import { t } from "../../i18n/pt-BR";
import { brlInt, monthLabel, pct, shiftMonth } from "../../lib/format";
import { transacoesLink } from "../../lib/links";
import "./inicio.css";

type MonthSummary = components["schemas"]["MonthSummary"];

const TOP = 5;
const TREND_MONTHS = 6;
const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

function summaryQuery(month: string | null) {
  return {
    queryKey: ["summary", month ?? "current"],
    queryFn: () => api<MonthSummary>(month ? `/summary/month?month=${month}` : "/summary/month"),
  };
}

function useTrend(to: string | undefined) {
  return useQuery({
    queryKey: ["trend", TREND_MONTHS, to],
    queryFn: () => api<TrendPoint[]>(`/trend?months=${TREND_MONTHS}&to=${to}`),
    enabled: !!to,
    placeholderData: keepPreviousData,
  });
}

/** Header for `month`; built from the current summary only, so it stays put while another month loads or fails. */
function MonthHeader({ month, current, first, onPick }: { month: string; current: MonthSummary; first?: string | null; onPick: (m: string) => void }) {
  const name = monthLabel(month);
  const isCurrent = month === current.month;
  const label = isCurrent ? `${name} · ${t.home.dayOf(current.day, current.days_in_month)}` : `${name} ${month.slice(0, 4)}`;
  return (
    <header className="month-head">
      <button type="button" className="icon-btn" aria-label={t.home.prevMonth} disabled={!!first && month <= first} onClick={() => onPick(shiftMonth(month, -1))}>
        ‹
      </button>
      <h1 className="month-label" aria-live="polite">{label}</h1>
      <button
        type="button"
        className="icon-btn"
        aria-label={t.home.nextMonth}
        disabled={month >= current.month}
        onClick={() => onPick(shiftMonth(month, 1))}
      >
        ›
      </button>
    </header>
  );
}

function Hero({ s }: { s: MonthSummary }) {
  const { deficit, sobrou } = s.renda_split; // same source as the bar and its deficit flag
  const name = monthLabel(s.month).toLowerCase();
  const title = s.is_current
    ? deficit ? t.home.shortThisMonth : t.home.leftThisMonth
    : deficit ? t.home.shortIn(name) : t.home.leftIn(name);
  return (
    <div className="hero">
      <div className="hero-label">{title}</div>
      <div className={`hero-value ${deficit ? "is-short" : "is-left"}`}>{brlInt(Math.abs(sobrou))}</div>
      <div className="hero-sub">{t.home.ofIncome(brlInt(s.totals.income))}</div>
    </div>
  );
}

function ReviewCard({ n }: { n: number }) {
  if (n <= 0) return null;
  return (
    <Card href="/revisar" className="review-card">
      <div>
        <div className="review-count">{t.home.toReview(n)}</div>
        <div className="sub">{t.home.reviewTime}</div>
      </div>
      <span className="pill">{t.home.reviewAction}</span>
    </Card>
  );
}

function SpendingCard({ s }: { s: MonthSummary }) {
  const { spent, reference_to_date: ref } = s.spending;
  const ratio = ref > 0 ? spent / ref : null;
  const when = s.is_current ? t.home.untilDay(s.day) : t.home.inMonth;
  return (
    <Card title={t.home.vsUsual} action={ratio !== null ? pct(ratio) : undefined}>
      <div className="meter" role="img" aria-label={ratio !== null ? `${t.home.vsUsual}: ${pct(ratio)}` : t.home.noUsual}>
        <b style={{ width: `${Math.min(1, ratio ?? 0) * 100}%` }} className={ratio !== null && ratio > 1 ? "over" : undefined} />
      </div>
      <div className="note">{ref > 0 ? `${t.home.spentOf(brlInt(spent), brlInt(ref))} ${when}` : `${brlInt(spent)} · ${t.home.noUsual}`}</div>
    </Card>
  );
}

type Category = Taxonomy["categories"][number];

function slice(key: string, label: string, value: number, category?: Category): Slice {
  return { key, label, value, color: categoryColor(category), ink: categoryInk(category) };
}

/** Income by source (category, manual entries, uncategorized); hidden when the month has no income. */
function IncomeSourcesCard({ s, taxonomy }: { s: MonthSummary; taxonomy?: Taxonomy }) {
  if (s.totals.income <= 0 || s.income_sources.length === 0) return null;
  const byId = new Map(taxonomy?.categories.map((c) => [c.id, c]) ?? []);
  const slices = foldOther(s.income_sources.map((src) => slice(src.key, src.label, src.amount, byId.get(src.key))), TOP, t.home.otherSources);
  return (
    <Card href={`/transacoes?mes=${s.month}&linha=income`} title={t.home.whereIncomeFrom}>
      <IncomeSourcesBar slices={slices} manual={s.income_sources.some((src) => src.key.startsWith("manual:"))} />
    </Card>
  );
}

function Categories({ s, taxonomy }: { s: MonthSummary; taxonomy?: Taxonomy }) {
  const [all, setAll] = useState(false);
  const byId = new Map(taxonomy?.categories.map((c) => [c.id, c]) ?? []);
  const cats = s.categories.filter((c) => c.spent > 0);
  if (cats.length === 0) return <Card><p className="empty">{t.home.noSpending}</p></Card>;
  const shown = all ? cats : cats.slice(0, TOP);
  const ranked = [...cats].sort((a, b) => b.spent - a.spent);
  const slices = foldOther(ranked.map((c) => {
    const category = byId.get(c.category_id);
    return slice(c.category_id, categoryName(c.category_id, category), c.spent, category);
  }), TOP);
  return (
    <Card className="cats-card">
      <SpendingDonut slices={slices} />
      <ul className="cat-list">
        {shown.map((c) => (
          <CategoryRow key={c.category_id} status={c} category={byId.get(c.category_id)} />
        ))}
      </ul>
      {cats.length > TOP && (
        <button type="button" className="see-all" aria-expanded={all} onClick={() => setAll((v) => !v)}>
          <span>{all ? t.home.seeLess : t.home.seeAll(cats.length)}</span>
          <span aria-hidden="true">{all ? "‹" : "›"}</span>
        </button>
      )}
    </Card>
  );
}

const WIDE = "(min-width: 1024px)";

/** True on the desktop layout; false where matchMedia is missing (tests). The list is created once per mount. */
function useWide(): boolean {
  const [mq] = useState(() => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(WIDE) : null));
  const subscribe = useCallback(
    (cb: () => void) => {
      mq?.addEventListener("change", cb);
      return () => mq?.removeEventListener("change", cb);
    },
    [mq],
  );
  return useSyncExternalStore(subscribe, () => mq?.matches ?? false, () => false);
}

/** Desktop only (phones get the RendaBar card): the month's full Sankey; clicking a node opens its transactions. */
function SankeyCard({ month, taxonomy }: { month: string; taxonomy?: Taxonomy }) {
  const navigate = useNavigate();
  const q = useSankey(`month:${month}`);
  if (!q.data) return q.isError ? null : <Card title={t.sankey.title}><div className="chart-skeleton skeleton" /></Card>;
  return (
    <Card title={t.sankey.title} action={monthLabel(month)}>
      <Sankey
        data={q.data}
        categories={taxonomy?.categories}
        onNodeClick={(_key, filter) => navigate(transacoesLink(filter, { month }))}
      />
      <p className="note">{t.sankey.hint}</p>
    </Card>
  );
}

export function Inicio() {
  const wide = useWide();
  // useLocation + useNavigate rather than useSearchParams: the latter embeds an external polyfill URL
  // in its warning text, which the build's no-external-URL check rejects.
  const location = useLocation();
  const navigate = useNavigate();
  const params = new URLSearchParams(location.search);
  const raw = params.get("mes");
  const picked = raw && MONTH_RE.test(raw) ? raw : null;
  const current = useQuery(summaryQuery(null)); // latest month with data = the server's current month
  const latest = current.data?.month;
  const month = picked && latest && picked < latest ? picked : null;
  // One query whose key follows the month: keepPreviousData keeps the last figures on screen while the next one loads.
  const view = useQuery({ ...summaryQuery(month), enabled: !!latest, placeholderData: keepPreviousData });
  const s = view.data;
  const trend = useTrend(s?.month);
  const taxonomy = useTaxonomy();

  const pick = (m: string) => {
    const next = new URLSearchParams(params);
    if (latest && m >= latest) next.delete("mes");
    else next.set("mes", m);
    const q = next.toString();
    navigate({ pathname: location.pathname, search: q ? `?${q}` : "" }, { replace: true });
  };

  const errorText = (e: unknown) => (e instanceof Error ? e.message : t.genericError);
  if (!current.data) {
    return current.isError ? (
      <section className="inicio">
        <div className="card empty" role="alert">{errorText(current.error)}</div>
      </section>
    ) : (
      <section className="inicio" aria-busy="true">
        <Skeleton height={28} />
        <Skeleton height={120} />
        <Skeleton height={96} />
        <Skeleton height={160} />
      </section>
    );
  }
  const shown = month ?? current.data.month;
  const header = <MonthHeader month={shown} current={current.data} first={taxonomy.data?.first_month} onPick={pick} />;
  if (view.isError) {
    return (
      <section className="inicio">
        {header}
        <div className="card empty" role="alert">
          {errorText(view.error)}
          <p>
            <button type="button" className="link-btn" onClick={() => pick(current.data.month)}>
              {t.home.backToCurrent}
            </button>
          </p>
        </div>
      </section>
    );
  }
  if (!s) {
    return (
      <section className="inicio" aria-busy="true">
        {header}
        <Skeleton height={120} />
        <Skeleton height={160} />
      </section>
    );
  }
  const stale = view.isPlaceholderData;

  return (
    <section className="inicio" aria-busy={stale}>
      {header}
      <div className={`inicio-grid${stale ? " is-stale" : ""}`}>
        <div className="inicio-col">
          <div className="o-hero"><Hero s={s} /></div>
          <div className="o-income"><IncomeSourcesCard s={s} taxonomy={taxonomy.data} /></div>
          <div className="o-renda">
            <Card href="/panorama" title={t.home.whereIncomeWent}>
              <RendaBar split={s.renda_split} />
            </Card>
          </div>
          <div className="o-trend">
            <Card title={t.home.trendTitle} action={t.home.trendSpan(TREND_MONTHS)}>
              {trend.data ? <IncomeSpendBars points={trend.data} current={s.month} /> : <div className="chart-skeleton skeleton" />}
            </Card>
          </div>
        </div>
        <div className="inicio-col">
          <div className="o-review"><ReviewCard n={s.review_count} /></div>
          <div className="o-spend"><SpendingCard s={s} /></div>
          <div className="o-cats"><Categories s={s} taxonomy={taxonomy.data} /></div>
        </div>
        {wide && <div className="o-sankey"><SankeyCard month={s.month} taxonomy={taxonomy.data} /></div>}
      </div>
    </section>
  );
}
