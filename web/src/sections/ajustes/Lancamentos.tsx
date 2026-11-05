import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api } from "../../api/client";
import { invalidateAfterMutation } from "../../api/queries";
import { Card } from "../../components/Card";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Skeleton } from "../../components/Skeleton";
import { useToast } from "../../components/Toast";
import { t } from "../../i18n/pt-BR";
import { brl } from "../../lib/format";
import { parseAmount } from "../../lib/parse";

interface Entry {
  id: number;
  month: string;
  pnl_line: string;
  pnl_line_label: string;
  amount: number;
  note: string;
}

const NOTE_MAX = 500;
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
const LINES = Object.keys(t.settings.manual.lines);
const errText = (e: unknown) => (e instanceof Error ? e.message : t.genericError);

interface Draft { month: string; line: string; amount: string; note: string }
const EMPTY: Draft = { month: "", line: "", amount: "", note: "" };

/** Mirrors the API's checks (routes/settings.py) so obvious mistakes never leave the browser. */
function validate(d: Draft): Partial<Record<keyof Draft, string>> {
  const m = t.settings.manual.errors;
  const out: Partial<Record<keyof Draft, string>> = {};
  if (!MONTH.test(d.month.trim())) out.month = m.month;
  if (!LINES.includes(d.line)) out.line = m.line;
  const amount = parseAmount(d.amount);
  if (!Number.isFinite(amount) || amount === 0) out.amount = m.amount;
  const note = d.note.trim();
  if (!note) out.note = m.note;
  else if (note.length > NOTE_MAX) out.note = m.noteLong;
  return out;
}

export function Lancamentos() {
  const qc = useQueryClient();
  const toast = useToast();
  const entries = useQuery({ queryKey: ["manualEntries"], queryFn: () => api<Entry[]>("/manual-entries") });
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [errors, setErrors] = useState<Partial<Record<keyof Draft, string>>>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [pending, setPending] = useState<Entry | null>(null);

  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ["manualEntries"] }), invalidateAfterMutation(qc)]);
  const add = useMutation({
    mutationFn: (d: Draft) =>
      api<Entry>("/manual-entries", {
        method: "POST",
        body: JSON.stringify({ month: d.month.trim(), pnl_line: d.line, amount: parseAmount(d.amount), note: d.note.trim() }),
      }),
    onSuccess: async () => {
      setDraft(EMPTY);
      setApiError(null);
      toast.show(t.settings.manual.added);
      await refresh();
    },
    onError: (e) => setApiError(errText(e)),
  });
  const remove = useMutation({
    mutationFn: (e: Entry) => api<unknown>(`/manual-entries/${e.id}`, { method: "DELETE" }),
    onSuccess: async () => {
      setPending(null);
      toast.show(t.settings.manual.deleted);
      await refresh();
    },
    onError: (e) => {
      setPending(null);
      setApiError(errText(e));
    },
  });

  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    const found = validate(draft);
    setErrors(found);
    setApiError(null);
    if (Object.keys(found).length === 0) add.mutate(draft);
  };
  const set = (k: keyof Draft) => (v: string) => setDraft((d) => ({ ...d, [k]: v }));
  const m = t.settings.manual;

  return (
    <Card title={<h2 className="aj-h">{m.title}</h2>}>
      <p className="aj-hint">{m.hint}</p>
      {entries.isPending ? (
        <Skeleton height={60} />
      ) : (entries.data ?? []).length === 0 ? (
        <p className="aj-hint">{m.empty}</p>
      ) : (
        <ul className="aj-list">
          {entries.data!.map((e) => (
            <li key={e.id}>
              <span className="aj-entry">
                <b>{e.note}</b>
                <small>{e.month} · {e.pnl_line_label}</small>
              </span>
              <span className="aj-entry-end">
                <span className={e.amount < 0 ? "neg" : ""}>{brl(e.amount)}</span>
                <button type="button" className="btn small danger-text" aria-label={m.delete(e.note)} onClick={() => setPending(e)}>
                  {t.settings.delete}
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <form className="aj-form" onSubmit={submit} noValidate>
        <label>
          {m.month}
          <input type="text" placeholder="2026-10" value={draft.month} onChange={(e) => set("month")(e.target.value)} aria-invalid={!!errors.month} />
          {errors.month && <span className="aj-error">{errors.month}</span>}
        </label>
        <label>
          {m.line}
          <select value={draft.line} onChange={(e) => set("line")(e.target.value)} aria-invalid={!!errors.line}>
            <option value="" />
            {LINES.map((l) => <option key={l} value={l}>{m.lines[l]}</option>)}
          </select>
          {errors.line && <span className="aj-error">{errors.line}</span>}
        </label>
        <label>
          {m.amount}
          <input type="text" inputMode="decimal" placeholder={m.amountHint} value={draft.amount} onChange={(e) => set("amount")(e.target.value)} aria-invalid={!!errors.amount} />
          {errors.amount && <span className="aj-error">{errors.amount}</span>}
        </label>
        <label>
          {m.note}
          <input type="text" value={draft.note} maxLength={NOTE_MAX + 50} onChange={(e) => set("note")(e.target.value)} aria-invalid={!!errors.note} />
          {errors.note && <span className="aj-error">{errors.note}</span>}
        </label>
        {apiError && <p className="aj-error" role="alert">{apiError}</p>}
        <button type="submit" className="btn primary" disabled={add.isPending}>{m.add}</button>
      </form>

      {pending && (
        <ConfirmDialog title={m.confirmTitle} confirmLabel={t.settings.delete} busy={remove.isPending}
                       onConfirm={() => remove.mutate(pending)} onCancel={() => setPending(null)}>
          {m.confirmBody(pending.note, pending.month)}
        </ConfirmDialog>
      )}
    </Card>
  );
}
