import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { invalidateAfterMutation } from "../../api/queries";
import { Card } from "../../components/Card";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Skeleton } from "../../components/Skeleton";
import { useToast } from "../../components/Toast";
import { t } from "../../i18n/pt-BR";

interface Rule {
  id: string;
  category_id: string;
  category_label: string;
  conditions: Record<string, unknown>;
  priority: number;
}

function conditionText(key: string, value: unknown): string {
  const s = t.settings.rules;
  const name = s.keys[key] ?? key;
  if (key === "has_cnpj") return s.document;
  if (key === "direction") return `${name}: ${s.direction[String(value)] ?? String(value)}`;
  return `${name}: ${Array.isArray(value) ? value.join(", ") : String(value)}`;
}

export function Regras() {
  const qc = useQueryClient();
  const toast = useToast();
  const rules = useQuery({ queryKey: ["rules"], queryFn: () => api<Rule[]>("/rules") });
  const [pending, setPending] = useState<Rule | null>(null);
  const [error, setError] = useState<string | null>(null);

  const remove = useMutation({
    mutationFn: (r: Rule) => api<unknown>(`/rules/${encodeURIComponent(r.id)}`, { method: "DELETE" }),
    onSuccess: async () => {
      setPending(null);
      setError(null);
      toast.show(t.settings.rules.deleted);
      await Promise.all([qc.invalidateQueries({ queryKey: ["rules"] }), invalidateAfterMutation(qc)]);
    },
    onError: (e) => {
      setPending(null);
      setError(e instanceof Error ? e.message : t.genericError);
    },
  });

  return (
    <Card title={<h2 className="aj-h">{t.settings.rules.title}</h2>}>
      <p className="aj-hint">{t.settings.rules.hint}</p>
      {error && <p className="aj-error" role="alert">{error}</p>}
      {rules.isPending ? (
        <Skeleton height={60} />
      ) : (rules.data ?? []).length === 0 ? (
        <p className="aj-hint">{t.settings.rules.empty}</p>
      ) : (
        <ul className="aj-rules">
          {rules.data!.map((r) => (
            <li key={r.id}>
              <div className="aj-rule-head">
                <code>{r.id}</code>
                <span className="chip">{r.category_label}</span>
                <button type="button" className="btn small danger-text" aria-label={t.settings.rules.delete(r.id)} onClick={() => setPending(r)}>
                  {t.settings.delete}
                </button>
              </div>
              <ul className="aj-conds" aria-label={t.settings.rules.conditions}>
                {Object.entries(r.conditions).map(([k, v]) => <li key={k}>{conditionText(k, v)}</li>)}
              </ul>
            </li>
          ))}
        </ul>
      )}
      {pending && (
        <ConfirmDialog
          title={t.settings.rules.confirmTitle}
          confirmLabel={t.settings.delete}
          busy={remove.isPending}
          onConfirm={() => remove.mutate(pending)}
          onCancel={() => setPending(null)}
        >
          {t.settings.rules.confirmBody(pending.id, pending.category_label)}
        </ConfirmDialog>
      )}
    </Card>
  );
}
