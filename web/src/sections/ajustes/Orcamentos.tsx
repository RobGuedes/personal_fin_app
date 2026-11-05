import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../../api/client";
import { invalidateAfterMutation, usePanorama, useTaxonomy } from "../../api/queries";
import { Card } from "../../components/Card";
import { Skeleton } from "../../components/Skeleton";
import { useToast } from "../../components/Toast";
import { t } from "../../i18n/pt-BR";
import { brl } from "../../lib/format";
import { parseAmount } from "../../lib/parse";

const EXPENSE_LINES = ["expenses", "commissions"]; // same lines the API accepts

export function Orcamentos() {
  const qc = useQueryClient();
  const toast = useToast();
  const taxonomy = useTaxonomy();
  const panorama = usePanorama("last12");
  const budgets = useQuery({ queryKey: ["budgets"], queryFn: () => api<Record<string, number>>("/budgets") });
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  const rows = useMemo(() => {
    const usual = new Map((panorama.data?.categories ?? []).map((c) => [c.category_id, c.usual ?? c.monthly_avg]));
    return (taxonomy.data?.categories ?? [])
      .filter((c) => EXPENSE_LINES.includes(c.line))
      .map((c) => ({ id: c.id, label: c.label, suggestion: usual.get(c.id) ?? null }));
  }, [taxonomy.data, panorama.data]);

  const setError = (id: string, msg: string | null) =>
    setErrors((e) => {
      const { [id]: _drop, ...rest } = e;
      return msg ? { ...rest, [id]: msg } : rest;
    });
  const clearDraft = (id: string) =>
    setDrafts((d) => {
      const { [id]: _drop, ...rest } = d;
      return rest;
    });

  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ["budgets"] }), invalidateAfterMutation(qc)]);
  const save = useMutation({
    mutationFn: (v: { id: string; label: string; amount: number }) =>
      api<unknown>(`/budgets/${encodeURIComponent(v.id)}`, { method: "PUT", body: JSON.stringify({ monthly_amount: v.amount }) }),
    onSuccess: async (_r, v) => {
      clearDraft(v.id);
      setError(v.id, null);
      toast.show(t.settings.budgets.saved(v.label));
      await refresh();
    },
    onError: (e, v) => setError(v.id, e instanceof Error ? e.message : t.genericError),
  });
  const clear = useMutation({
    mutationFn: (v: { id: string; label: string }) => api<unknown>(`/budgets/${encodeURIComponent(v.id)}`, { method: "DELETE" }),
    onSuccess: async (_r, v) => {
      clearDraft(v.id);
      setError(v.id, null);
      toast.show(t.settings.budgets.cleared(v.label));
      await refresh();
    },
    onError: (e, v) => setError(v.id, e instanceof Error ? e.message : t.genericError),
  });

  const saved = budgets.data ?? {};
  const loading = taxonomy.isPending || budgets.isPending;
  return (
    <Card title={<h2 className="aj-h">{t.settings.budgets.title}</h2>}>
      <p className="aj-hint">{t.settings.budgets.hint}</p>
      {loading ? (
        <Skeleton height={80} />
      ) : rows.length === 0 ? (
        <p className="aj-hint">{t.settings.budgets.empty}</p>
      ) : (
        <ul className="aj-budgets">
          {rows.map((r) => {
            const hasBudget = saved[r.id] !== undefined;
            const initial = hasBudget ? saved[r.id] : r.suggestion !== null ? Math.round(r.suggestion) : null;
            const value = drafts[r.id] ?? (initial === null ? "" : String(initial));
            const dirty = !hasBudget || drafts[r.id] !== undefined;
            return (
              <li key={r.id}>
                <div className="aj-budget-row">
                  <span className="aj-budget-name">{r.label}</span>
                  {r.suggestion !== null && <small>{t.settings.budgets.usual(brl(r.suggestion))}</small>}
                  <input
                    type="text"
                    inputMode="decimal"
                    aria-label={t.settings.budgets.input(r.label)}
                    value={value}
                    onChange={(e) => setDrafts((d) => ({ ...d, [r.id]: e.target.value }))}
                  />
                  <button
                    type="button"
                    className="btn small primary"
                    aria-label={t.settings.budgets.save(r.label)}
                    disabled={!dirty || save.isPending}
                    onClick={() => {
                      const amount = parseAmount(value);
                      if (!(amount > 0)) return setError(r.id, t.settings.budgets.invalid);
                      setError(r.id, null);
                      save.mutate({ id: r.id, label: r.label, amount });
                    }}
                  >
                    {t.settings.save}
                  </button>
                  {hasBudget && (
                    <button type="button" className="btn small" aria-label={t.settings.budgets.clear(r.label)} disabled={clear.isPending}
                            onClick={() => clear.mutate({ id: r.id, label: r.label })}>
                      ×
                    </button>
                  )}
                </div>
                {errors[r.id] && <p className="aj-error" role="alert">{errors[r.id]}</p>}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
