import { useState } from "react";
import { useContributions, useCurrentMonth, useNetWorth, useNetWorthHistory, type NetWorthResponse } from "../../api/queries";
import { AreaChart } from "../../charts/AreaChart";
import { ContributionBars } from "../../charts/ContributionBars";
import { Card } from "../../components/Card";
import { Skeleton } from "../../components/Skeleton";
import { t } from "../../i18n/pt-BR";
import { brl, brlSigned, dateBR } from "../../lib/format";
import "./patrimonio.css";

const errText = (e: unknown) => (e instanceof Error ? e.message : t.genericError);

function Group({ g }: { g: NetWorthResponse["groups"][number] }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="wgroup">
      <button type="button" className="wgroup-head" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="chev" aria-hidden="true">{open ? "▾" : "▸"}</span>
        <span className="wgroup-name">{g.label}</span>
        <b className={g.value < 0 ? "is-neg" : undefined}>{brl(g.value)}</b>
      </button>
      {open && (
        <ul className="waccounts">
          {g.accounts.map((a, i) => (
            <li key={`${a.label}-${i}`}>
              <span className="wacc-name">
                {a.label}
                {a.updated_at && <small>{t.wealth.updated(dateBR(a.updated_at))}</small>}
              </span>
              <span className={a.value < 0 ? "is-neg" : undefined}>{brl(a.value)}</span>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function Contributions({ month }: { month: string }) {
  const year = month.slice(0, 4);
  const q = useContributions(`year:${year}`);
  const d = q.data;
  return (
    <Card title={t.wealth.contributions} action={year}>
      {q.isError ? (
        <p className="empty" role="alert">{errText(q.error)}</p>
      ) : !d ? (
        <Skeleton height={80} />
      ) : (
        <>
          <div className="contrib-total">{brl(d.total)}</div>
          <div className="sub">{t.wealth.contributionsNote}</div>
          <ContributionBars points={d.months.map((m) => ({ month: m, value: d.values[m] ?? 0 }))} current={month} />
        </>
      )}
    </Card>
  );
}

export function Patrimonio() {
  const nw = useNetWorth();
  const hist = useNetWorthHistory();
  const cur = useCurrentMonth();
  const points = (hist.data ?? []).map((p) => ({ date: p.date, value: p.total }));
  const first = points[0];
  const last = points[points.length - 1];
  const change = points.length >= 2 ? last.value - first.value : null;

  return (
    <section className="patrimonio">
      <h1>{t.wealth.title}</h1>
      {nw.isError ? (
        <div className="card empty" role="alert">{errText(nw.error)}</div>
      ) : !nw.data ? (
        <Skeleton height={120} />
      ) : (
        <Card>
          <div className="sub">{t.wealth.netWorth}</div>
          <div className="nw-total">{brl(nw.data.total)}</div>
          {change !== null && (
            <div className="sub">
              <span className={change < 0 ? "is-neg" : "is-pos"}>{brlSigned(change)}</span> {t.wealth.since(dateBR(first.date).slice(0, 5))}
            </div>
          )}
          {hist.isError ? (
            <p className="empty" role="alert">{errText(hist.error)}</p>
          ) : !hist.data ? (
            <Skeleton height={110} />
          ) : points.length < 2 ? (
            <p className="empty">{t.wealth.emptyHistory}</p>
          ) : (
            <AreaChart points={points} label={t.wealth.chart} />
          )}
        </Card>
      )}
      {nw.data && (
        <Card className="wgroups">
          <ul className="wgroup-list">{nw.data.groups.map((g) => <Group key={g.grp} g={g} />)}</ul>
        </Card>
      )}
      {cur.isError ? (
        <div className="card empty" role="alert">{errText(cur.error)}</div>
      ) : !cur.data ? (
        <Skeleton height={120} />
      ) : (
        <Contributions month={cur.data.month} />
      )}
    </section>
  );
}
