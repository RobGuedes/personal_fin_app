import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { Card } from "../../components/Card";
import { Skeleton } from "../../components/Skeleton";
import { t } from "../../i18n/pt-BR";
import { amountSigned, dateBR, pct } from "../../lib/format";

interface Transfer {
  link_type: string;
  link_label: string;
  confidence: number | null;
  from_date: string;
  from_account: string;
  from_description: string;
  from_amount: number;
  to_date: string | null;
  to_account: string | null;
  to_description: string | null;
  to_amount: number | null;
}

const SHOWN = 10;

function Leg({ title, date, account, description, amount }: { title: string; date: string; account: string; description: string; amount: number }) {
  return (
    <div className="aj-leg">
      <small>{title} · {dateBR(date)}</small>
      <span>{account}</span>
      <span className="aj-desc">{description}</span>
      <b>{amountSigned(amount)}</b>
    </div>
  );
}

export function Auditoria() {
  const q = useQuery({ queryKey: ["transfers"], queryFn: () => api<Transfer[]>("/transfers") });
  const [all, setAll] = useState(false);
  const rows = q.data ?? [];
  const shown = all ? rows : rows.slice(0, SHOWN);
  return (
    <Card title={<h2 className="aj-h">{t.settings.audit.title}</h2>}>
      <p className="aj-hint">{t.settings.audit.hint}</p>
      {q.isPending ? (
        <Skeleton height={60} />
      ) : rows.length === 0 ? (
        <p className="aj-hint">{t.settings.audit.empty}</p>
      ) : (
        <ul className="aj-audit">
          {shown.map((r, i) => (
            <li key={i}>
              <div className="aj-audit-head">
                <b>{r.link_label}</b>
                {r.confidence !== null && r.confidence < 1 && <small>{t.settings.audit.confidence(pct(r.confidence))}</small>}
              </div>
              <Leg title={t.settings.audit.from} date={r.from_date} account={r.from_account} description={r.from_description} amount={r.from_amount} />
              {r.to_date && r.to_account !== null && r.to_amount !== null ? (
                <Leg title={t.settings.audit.to} date={r.to_date} account={r.to_account} description={r.to_description ?? ""} amount={r.to_amount} />
              ) : (
                <small className="aj-hint">{t.settings.audit.noPair}</small>
              )}
            </li>
          ))}
        </ul>
      )}
      {rows.length > SHOWN && (
        <button type="button" className="btn" aria-expanded={all} onClick={() => setAll((v) => !v)}>
          {all ? t.settings.audit.showLess : t.settings.audit.showAll(rows.length)}
        </button>
      )}
    </Card>
  );
}
