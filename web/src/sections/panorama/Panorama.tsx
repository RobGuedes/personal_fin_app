import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import {
  useChannels, useCounterparties, useCurrentMonth, usePanorama, usePnl, useSankey, useTaxonomy, type PanoramaResponse, type Taxonomy,
} from "../../api/queries";
import { Sankey } from "../../charts/Sankey";
import { Card } from "../../components/Card";
import { categoryColor, categoryIcon } from "../../components/CategoryRow";
import { Skeleton } from "../../components/Skeleton";
import { t } from "../../i18n/pt-BR";
import { brlCompact, pct } from "../../lib/format";
import { transacoesLink } from "../../lib/links";
import { Canais } from "./Canais";
import { Demonstrativo } from "./Demonstrativo";
import { QuemRecebe } from "./QuemRecebe";
import { Sparkline } from "./Sparkline";
import { apiPeriod, parseKind, singleMonth, type PeriodKind } from "./period";
import "./panorama.css";

const KINDS: { kind: PeriodKind; label: string }[] = [
  { kind: "mes", label: t.panorama.month },
  { kind: "12m", label: t.panorama.last12 },
  { kind: "ano", label: t.panorama.year },
];
const TABS = [
  { id: "demonstrativo", label: t.panorama.demonstrativo },
  { id: "canais", label: t.panorama.channels },
  { id: "quem", label: t.panorama.counterparties },
] as const;
type TabId = (typeof TABS)[number]["id"];

const PHONE = "(max-width: 767px)";

/** True on phones; false where matchMedia is missing (tests). */
function usePhone(): boolean {
  const mq = typeof window !== "undefined" && window.matchMedia ? window.matchMedia(PHONE) : null;
  const [phone, setPhone] = useState(mq?.matches ?? false);
  useEffect(() => {
    if (!mq) return;
    const on = () => setPhone(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [mq]);
  return phone;
}

function Kpis({ p }: { p: PanoramaResponse }) {
  return (
    <div className="kpis">
      <div className="kpi">
        <div className="sub">{t.panorama.savingsRate}</div>
        <div className={`kpi-value${p.savings_rate !== null && p.savings_rate < 0 ? " is-short" : " is-left"}`}>
          {p.savings_rate === null ? "—" : pct(p.savings_rate)}
        </div>
        {p.savings_rate === null && <div className="sub">{t.panorama.noIncome}</div>}
      </div>
      <div className="kpi">
        <div className="sub">{t.panorama.avgIncome}</div>
        <div className="kpi-value">{brlCompact(p.avg_income)}</div>
      </div>
      <div className="kpi">
        <div className="sub">{t.panorama.avgSpending}</div>
        <div className="kpi-value">{brlCompact(p.avg_spending)}</div>
      </div>
    </div>
  );
}

function Categories({ p, taxonomy, kind }: { p: PanoramaResponse; taxonomy?: Taxonomy; kind: PeriodKind }) {
  const byId = new Map(taxonomy?.categories.map((c) => [c.id, c]) ?? []);
  return (
    <Card title={t.panorama.categories} action={t.panorama.trend}>
      {p.categories.length === 0 ? (
        <p className="empty">{t.panorama.noCategories}</p>
      ) : (
        <ul className="pcat-list">
          {p.categories.map((c) => {
            const cat = byId.get(c.category_id);
            return (
              <li key={c.category_id}>
                <Link to={`/panorama/categoria/${encodeURIComponent(c.category_id)}?periodo=${kind}`} className="pcat">
                  <span className="cat-dot" style={{ background: `color-mix(in srgb, ${categoryColor(cat)} 18%, var(--card))` }} aria-hidden="true">
                    {categoryIcon(c.category_id, cat)}
                  </span>
                  <span className="pcat-name">{c.label}</span>
                  <Sparkline values={c.sparkline} color={categoryColor(cat)} label={c.label} />
                  <b>{`${brlCompact(c.monthly_avg)}${t.panorama.perMonth}`}</b>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      <p className="note">{t.panorama.categoriesHint}</p>
    </Card>
  );
}

function SankeyCard({ period, kind, month, taxonomy }: { period: string | null; kind: PeriodKind; month?: string; taxonomy?: Taxonomy }) {
  const navigate = useNavigate();
  const phone = usePhone();
  const q = useSankey(period);
  if (!q.data) return q.isError ? null : <Card title={t.sankey.title}><div className="chart-skeleton skeleton" /></Card>;
  return (
    <Card title={t.sankey.title}>
      <Sankey
        data={q.data}
        categories={taxonomy?.categories}
        compact={phone}
        onOpen={() => navigate(`/panorama?fluxo=1&periodo=${kind}`)}
        onNodeClick={(_key, filter) => navigate(transacoesLink(filter, { month }))}
      />
      <p className="note">{phone ? t.sankey.openFull : t.sankey.hint}</p>
    </Card>
  );
}

/** Full-screen-ish Sankey for phones; wider than the viewport so rotating the phone helps. */
function FlowView({ period, kind, month, taxonomy }: { period: string | null; kind: PeriodKind; month?: string; taxonomy?: Taxonomy }) {
  const navigate = useNavigate();
  const q = useSankey(period);
  return (
    <section className="panorama flow-view">
      <header className="flow-head">
        <h1>{t.panorama.flowTitle}</h1>
        <button type="button" className="icon-btn" aria-label={t.panorama.closeFlow} onClick={() => navigate(`/panorama?periodo=${kind}`)}>
          ✕
        </button>
      </header>
      <p className="note">{t.panorama.flowHint}</p>
      {q.data ? (
        <div className="flow-scroll">
          <div className="flow-inner">
            <Sankey data={q.data} categories={taxonomy?.categories} onNodeClick={(_k, f) => navigate(transacoesLink(f, { month }))} />
          </div>
        </div>
      ) : q.isError ? (
        <div className="card empty" role="alert">{q.error instanceof Error ? q.error.message : t.genericError}</div>
      ) : (
        <Skeleton height={280} />
      )}
    </section>
  );
}

function Details({ period }: { period: string | null }) {
  const [tab, setTab] = useState<TabId>("demonstrativo");
  const pnl = usePnl(period, tab === "demonstrativo");
  const channels = useChannels(period, tab === "canais");
  const people = useCounterparties(period, tab === "quem");
  const state = tab === "demonstrativo" ? pnl : tab === "canais" ? channels : people;
  return (
    <Card className="details-card">
      <div className="seg" role="tablist" aria-label={t.panorama.tabs}>
        {TABS.map((x) => (
          <button key={x.id} type="button" role="tab" id={`tab-${x.id}`} aria-selected={tab === x.id} aria-controls="panorama-panel"
                  className={tab === x.id ? "on" : undefined} onClick={() => setTab(x.id)}>
            {x.label}
          </button>
        ))}
      </div>
      <div id="panorama-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} aria-busy={state.isFetching}>
        {state.isError ? (
          <p className="empty" role="alert">{state.error instanceof Error ? state.error.message : t.genericError}</p>
        ) : !state.data ? (
          <Skeleton height={160} />
        ) : tab === "demonstrativo" && pnl.data ? (
          <Demonstrativo data={pnl.data} />
        ) : tab === "canais" && channels.data ? (
          <Canais data={channels.data} />
        ) : tab === "quem" && people.data ? (
          <QuemRecebe data={people.data} />
        ) : null}
      </div>
    </Card>
  );
}

export function Panorama() {
  // useLocation + useNavigate rather than useSearchParams (its warning text embeds an external URL; see Inicio).
  const location = useLocation();
  const navigate = useNavigate();
  const params = new URLSearchParams(location.search);
  const kind = parseKind(params.get("periodo"));
  const current = useCurrentMonth();
  const period = apiPeriod(kind, current.data?.month);
  const month = singleMonth(kind, current.data?.month);
  const taxonomy = useTaxonomy();
  const panorama = usePanorama(period);
  const pick = (k: PeriodKind) => navigate({ pathname: location.pathname, search: k === "12m" ? "" : `?periodo=${k}` }, { replace: true });

  if (params.get("fluxo") === "1") return <FlowView period={period} kind={kind} month={month} taxonomy={taxonomy.data} />;
  const p = panorama.data;
  return (
    <section className="panorama" aria-busy={panorama.isPlaceholderData}>
      <h1>{t.panorama.title}</h1>
      <div className="seg" role="tablist" aria-label={t.panorama.period}>
        {KINDS.map((k) => (
          <button key={k.kind} type="button" role="tab" aria-selected={kind === k.kind} className={kind === k.kind ? "on" : undefined}
                  onClick={() => pick(k.kind)}>
            {k.label}
          </button>
        ))}
      </div>
      {panorama.isError && !p ? (
        <div className="card empty" role="alert">{panorama.error instanceof Error ? panorama.error.message : t.genericError}</div>
      ) : !p ? (
        <>
          <Skeleton height={72} />
          <Skeleton height={200} />
        </>
      ) : (
        <div className={`panorama-grid${panorama.isPlaceholderData ? " is-stale" : ""}`}>
          <Kpis p={p} />
          <SankeyCard period={period} kind={kind} month={month} taxonomy={taxonomy.data} />
          <Categories p={p} taxonomy={taxonomy.data} kind={kind} />
          <Details period={period} />
        </div>
      )}
    </section>
  );
}
