import { useMutation, useQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { api } from "../../api/client";
import { invalidateAfterMutation, useTaxonomy } from "../../api/queries";
import type { components } from "../../api/schema";
import { CategoryPicker, type Direction } from "../../components/CategoryPicker";
import { categoryName } from "../../components/CategoryRow";
import { useToast } from "../../components/Toast";
import { t } from "../../i18n/pt-BR";
import { amountSigned, brl, brlSigned, dateBR, dayLabel, monthLabel } from "../../lib/format";
import { UNCATEGORIZED } from "./Filters";
import { TxIcon, txCategoryText, txName, type TxOut } from "./TxRow";

export type TxDetail = components["schemas"]["TxDetail"];
type TxPage = components["schemas"]["TxPage"];
type TxPatch = components["schemas"]["TxPatch"];
type RuleOut = components["schemas"]["RuleOut"];

const errorText = (e: unknown) => (e instanceof Error ? e.message : t.genericError);
export const detailKey = (id: string) => ["transactions", "detail", id] as const;

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** The list row fields of a detail: what replaces the row in the cached pages after an edit. */
function toRow(d: TxDetail): TxOut {
  const { pluggy_category: _p, transfer_pair: _t, suggestion: _s, ...row } = d;
  return row;
}

interface TxSheetProps {
  id: string;
  onClose: () => void;
  /** Open another transaction in the sheet (the transfer pair). */
  onOpen: (id: string) => void;
  /** Category chips for a direction (most used in the loaded list first). */
  topFor: (direction: Direction) => string[];
}

/** Detail of one transaction: a bottom sheet on the phone, a side panel on the computer. Escape or the backdrop closes
 *  it; focus stays inside while it is open (the caller returns it to the row). */
export function TxSheet({ id, onClose, onOpen, topFor }: TxSheetProps) {
  const qc = useQueryClient();
  const toast = useToast();
  const taxonomy = useTaxonomy();
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const detail = useQuery({ queryKey: detailKey(id), queryFn: () => api<TxDetail>(`/transactions/${encodeURIComponent(id)}`) });
  const d = detail.data;
  const byId = new Map(taxonomy.data?.categories.map((c) => [c.id, c]) ?? []);
  const label = (cid: string) => categoryName(cid, byId.get(cid));

  // Note: edited locally, saved on blur when it changed. A server value replaces the field only when the field is not
  // dirty, i.e. it still holds the last server value or exactly what was sent (text typed during a save survives).
  const [note, setNote] = useState("");
  const noteRef = useRef(note);
  noteRef.current = note;
  const synced = useRef<{ id: string; note: string } | null>(null); // last server note applied to the field
  const sentNote = useRef<string | null>(null); // the note last sent, so blur + close do not send it twice
  useEffect(() => {
    if (!d) return;
    const server = d.note ?? "";
    const prev = synced.current;
    if (prev?.id === d.id && prev.note === server) return;
    if (prev?.id !== d.id) {
      sentNote.current = null; // another transaction: always load its note
      setNote(server);
    } else {
      const field = noteRef.current.trim();
      const clean = field === prev.note || (sentNote.current !== null && field === sentNote.current);
      if (clean) setNote(server);
    }
    synced.current = { id: d.id, note: server };
  }, [d]);

  const applyDetail = (next: TxDetail) => {
    qc.setQueryData(detailKey(next.id), next);
    const row = toRow(next);
    qc.setQueriesData<InfiniteData<TxPage>>({ queryKey: ["transactions", "list"] }, (data) =>
      data && {
        ...data,
        pages: data.pages.map((p) => ({ ...p, items: p.items.map((x) => (x.id === row.id ? row : x)) })),
      },
    );
  };

  const patchTx = (body: TxPatch) =>
    api<TxDetail>(`/transactions/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) });
  const patchCategory = useMutation({
    mutationFn: (categoryId: string) => patchTx({ category_id: categoryId }),
    onSuccess: (next, categoryId) => {
      applyDetail(next);
      toast.show(t.tx.sheet.classifiedAs(next.category_label ?? label(categoryId)));
      void invalidateAfterMutation(qc);
    },
    onError: (e) => toast.show(errorText(e)),
  });
  const patchNote = useMutation({
    mutationFn: (value: string | null) => patchTx({ note: value }),
    onSuccess: (next) => {
      applyDetail(next);
      toast.show(t.tx.sheet.noteSaved);
      void invalidateAfterMutation(qc);
    },
    onError: (e) => {
      sentNote.current = null;
      toast.show(errorText(e));
    },
  });

  const rule = useMutation({
    mutationFn: (categoryId: string) =>
      api<RuleOut>("/rules", { method: "POST", body: JSON.stringify({ transaction_id: id, category_id: categoryId }) }),
    onSuccess: (r) => {
      toast.show(t.tx.sheet.ruleCreated(r.rule_id));
      void invalidateAfterMutation(qc);
    },
    onError: (e) => toast.show(errorText(e)),
  });

  const saveNote = () => {
    if (!d) return;
    const next = note.trim();
    if (next === (sentNote.current ?? d.note ?? "")) return;
    sentNote.current = next;
    patchNote.mutate(next || null);
  };

  // Closing saves a note still being typed (blur does not fire when the sheet unmounts).
  const closeSheet = () => {
    saveNote();
    onClose();
  };
  const closeSheetRef = useRef(closeSheet);
  closeSheetRef.current = closeSheet;

  // Focus: into the sheet on open; Tab cycles inside; Escape closes (unless a child, e.g. the picker search, used it).
  useEffect(() => {
    closeRef.current?.focus();
  }, [id]);
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.defaultPrevented) return;
      if (ev.key === "/") {
        ev.stopPropagation(); // the global "/" would focus the search box behind the modal
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        closeSheetRef.current();
      } else if (ev.key === "Tab" && panelRef.current) {
        const els = [...panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
        if (els.length === 0) return;
        const first = els[0];
        const last = els[els.length - 1];
        const inside = panelRef.current.contains(document.activeElement);
        if (ev.shiftKey && (document.activeElement === first || !inside)) {
          ev.preventDefault();
          last.focus();
        } else if (!ev.shiftKey && (document.activeElement === last || !inside)) {
          ev.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, []);

  const direction: Direction = d && d.amount > 0 ? "in" : "out";
  const category = d && d.category_id !== UNCATEGORIZED ? d.category_id : null;
  return (
    <div className="txs-root">
      <div className="txs-backdrop" onClick={closeSheet} aria-hidden="true" />
      <div ref={panelRef} className="txs-panel" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="txs-grab" aria-hidden="true" />
        <header className="txs-head">
          {d ? <TxIcon category={byId.get(d.category_id)} size="lg" /> : <span className="tx-dot tx-dot-lg" aria-hidden="true" />}
          <h2 id={titleId} className="txs-title">{d ? txName(d) : t.tx.sheet.details}</h2>
          <button ref={closeRef} type="button" className="icon-btn" aria-label={t.close} onClick={closeSheet}>×</button>
        </header>

        {detail.isPending && <div className="txs-body"><div className="skeleton txs-skel" aria-hidden="true" /><p className="sub">{t.loading}</p></div>}
        {detail.isError && <div className="txs-body"><p className="sub">{errorText(detail.error)}</p></div>}

        {d && (
          <div className="txs-body">
            <div className={`txs-amount${d.amount > 0 && !d.excluded ? " is-in" : ""}${d.excluded ? " is-excluded" : ""}`}>
              {d.excluded ? brl(Math.abs(d.amount)) : brlSigned(d.amount)}
            </div>
            <div className="sub">
              {dayLabel(d.date)} · {d.account}
              {d.installment && <span className="tx-badge">{d.installment}</span>}
            </div>
            <div className="txs-tags">
              <span className="txs-tag">{txCategoryText(d)}</span>
              {d.excluded && <span className="txs-tag is-muted">{t.tx.sheet.excludedHint}</span>}
              {d.in_review && <span className="txs-tag is-review">{t.tx.sheet.inReview}</span>}
            </div>

            <section className="txs-section" aria-label={t.tx.sheet.category}>
              <h3 className="txs-label">{t.tx.sheet.category}</h3>
              <CategoryPicker
                direction={direction}
                value={category}
                top={topFor(direction)}
                onChange={(cid) => {
                  if (cid !== d.category_id && !patchCategory.isPending) patchCategory.mutate(cid);
                }}
              />
            </section>

            <section className="txs-section">
              <label className="txs-label" htmlFor={`${titleId}-note`}>{t.tx.sheet.note}</label>
              <textarea
                id={`${titleId}-note`}
                className="txs-note"
                rows={2}
                placeholder={t.tx.sheet.notePlaceholder}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                onBlur={saveNote}
              />
            </section>

            <section className="txs-section txs-rule">
              <button
                type="button"
                className="txs-btn"
                disabled={!category || rule.isPending}
                onClick={() => category && rule.mutate(category)}
              >
                {t.tx.sheet.createRule}
              </button>
              <span className="sub">{t.tx.sheet.createRuleHint}</span>
            </section>

            {d.transfer_pair && (
              <section className="txs-section">
                <h3 className="txs-label">{t.tx.sheet.transferPair}</h3>
                <button type="button" className="txs-pair" onClick={() => onOpen(d.transfer_pair!.id)}>
                  <TxIcon category={byId.get(d.transfer_pair.category_id)} />
                  <span className="tx-mid">
                    <span className="tx-name"><span className="tx-name-text">{txName(d.transfer_pair)}</span></span>
                    <span className="tx-sub">{dayLabel(d.transfer_pair.date)} · {d.transfer_pair.account}</span>
                  </span>
                  <span className="tx-amount">{amountSigned(d.transfer_pair.amount)}</span>
                </button>
              </section>
            )}

            <dl className="txs-fields">
              <Field k={t.tx.sheet.description} v={d.description} />
              <Field k={t.tx.sheet.account} v={d.account} />
              <Field k={t.tx.sheet.date} v={dateBR(d.date)} />
              {d.month !== d.date.slice(0, 7) && <Field k={t.tx.sheet.month} v={`${monthLabel(d.month)} ${d.month.slice(0, 4)}`} />}
              {d.method && <Field k={t.tx.sheet.method} v={t.review.methods[d.method] ?? d.method} />}
              {d.installment && <Field k={t.tx.sheet.installment} v={d.installment} />}
              {d.source && <Field k={t.tx.sheet.source} v={t.tx.sources[d.source] ?? d.source} />}
              <Field k={t.tx.sheet.pluggy} v={d.pluggy_category ?? "—"} />
              {d.suggestion && <Field k={t.tx.sheet.suggestion} v={`${byId.get(d.suggestion)?.icon ?? ""} ${label(d.suggestion)}`.trim()} />}
            </dl>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ k, v }: { k: string; v: string }) {
  return (
    <div className="txs-field">
      <dt>{k}</dt>
      <dd>{v}</dd>
    </div>
  );
}
