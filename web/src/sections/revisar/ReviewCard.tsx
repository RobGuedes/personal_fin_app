import { useEffect, useRef, useState, type FormEvent, type PointerEvent } from "react";
import { useTaxonomy } from "../../api/queries";
import type { components } from "../../api/schema";
import { CategoryPicker, OWN_TRANSFER, type Direction } from "../../components/CategoryPicker";
import { t } from "../../i18n/pt-BR";
import { brl, dayLabel } from "../../lib/format";

export type ReviewItem = components["schemas"]["ReviewItem"];
export interface ConfirmInput {
  category_id: string;
  create_rule: boolean;
  note?: string;
}

const SWIPE_PX = 80;
const MAX_CHIPS = 9;

/** Text entry has the keyboard: shortcuts stay off there (checkboxes and buttons are not text entry). */
export function isTextEntry(el: EventTarget | null): boolean {
  const e = el as HTMLElement | null;
  if (!e || !e.tagName) return false;
  if (e.isContentEditable || e.tagName === "TEXTAREA" || e.tagName === "SELECT") return true;
  if (e.tagName !== "INPUT") return false;
  return !["checkbox", "radio", "button", "submit", "reset", "range", "color"].includes((e as HTMLInputElement).type);
}

function shorten(s: string, max = 22): string {
  return s.length > max ? `${s.slice(0, max - 1).trimEnd()}…` : s;
}

function reducedMotion(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

interface ReviewCardProps {
  item: ReviewItem;
  busy: boolean;
  onConfirm: (input: ConfirmInput) => void;
  onSkip: () => void;
}

export function ReviewCard({ item, busy, onConfirm, onSkip }: ReviewCardProps) {
  const taxonomy = useTaxonomy();
  const cats = taxonomy.data?.categories ?? [];
  const byId = new Map(cats.map((c) => [c.id, c]));
  const direction: Direction = item.amount > 0 ? "in" : "out";
  const current = byId.has(item.category_id) ? item.category_id : null; // low-confidence classification, if any
  const initial = item.suggestion && byId.has(item.suggestion.category_id) ? item.suggestion.category_id : current;

  // Chips are fixed per card so 1–9 keep pointing at the same category after a pick.
  const [chips] = useState<string[]>(() => {
    // top_categories is already direction-aware (most used for inflows / outflows); unknown ids are dropped.
    const ids = [...(initial ? [initial] : []), ...item.top_categories.filter((id) => byId.has(id)), OWN_TRANSFER];
    return [...new Set(ids)].slice(0, MAX_CHIPS);
  });
  const [selected, setSelected] = useState<string | null>(initial);
  const [rule, setRule] = useState(false);
  const [note, setNote] = useState("");
  const [dx, setDx] = useState(0);
  const drag = useRef<{ id: number; x: number; y: number; dx: number } | null>(null);

  const submit = () => {
    if (busy || !selected) return;
    const n = note.trim();
    onConfirm({ category_id: selected, create_rule: rule, ...(n ? { note: n } : {}) });
  };
  const submitRef = useRef(submit);
  submitRef.current = submit;
  const skip = () => {
    if (!busy) onSkip(); // no skip while a confirm/undo runs (it would count the card twice)
  };
  const skipRef = useRef(skip);
  skipRef.current = skip;

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.metaKey || ev.ctrlKey || ev.altKey || isTextEntry(ev.target)) return;
      const target = ev.target as HTMLElement | null;
      if (ev.key === "Enter") {
        // Buttons and links keep their own Enter (Confirmar submits the form); chips confirm the selection.
        const native = target?.closest?.("button, a, [role=option]") && !target.closest("[data-chip]");
        if (native) return;
        ev.preventDefault();
        submitRef.current();
      } else if (/^[1-9]$/.test(ev.key)) {
        const id = chips[Number(ev.key) - 1];
        if (id) {
          ev.preventDefault();
          setSelected(id);
        }
      } else if (ev.key === "s" || ev.key === "S") {
        ev.preventDefault();
        skipRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [chips]);

  // Swipe right to confirm (touch and pen only; a mouse drag would fight text selection).
  const onPointerDown = (e: PointerEvent<HTMLFormElement>) => {
    if (e.pointerType === "mouse" || isTextEntry(e.target)) return;
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, dx: 0 };
  };
  const onPointerMove = (e: PointerEvent<HTMLFormElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    const mx = e.clientX - d.x;
    const my = e.clientY - d.y;
    d.dx = Math.abs(mx) > Math.abs(my) ? Math.max(0, mx) : 0;
    setDx(d.dx);
  };
  const endDrag = (e: PointerEvent<HTMLFormElement>, commit: boolean) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    drag.current = null;
    setDx(0);
    if (commit && d.dx > SWIPE_PX) submitRef.current();
  };

  const onFormSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit();
  };

  const name = item.counterparty || item.description;
  const method = item.method ? t.review.methods[item.method] ?? item.method : null;
  const meta = [item.counterparty ? item.description : method, item.account, dayLabel(item.date)].filter(Boolean).join(" · ");
  const shown = item.suggestion && byId.has(item.suggestion.category_id) ? byId.get(item.suggestion.category_id) : current ? byId.get(current) : undefined;
  const armed = dx > SWIPE_PX;
  const style = dx > 0 && !reducedMotion() ? { transform: `translateX(${dx}px) rotate(${Math.min(dx, 160) / 40}deg)` } : undefined;

  return (
    <form
      className={`card review-tx${armed ? " is-armed" : ""}${dx > 0 ? " is-dragging" : ""}`}
      aria-label={name}
      onSubmit={onFormSubmit}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={(e) => endDrag(e, true)}
      onPointerCancel={(e) => endDrag(e, false)}
      style={style}
    >
      <div className="rv-top">
        <span className="rv-dot" aria-hidden="true">{direction === "in" ? "↙︎" : "↗︎"}</span>
        <span className={`rv-amount${direction === "in" ? " is-in" : ""}`}>{brl(item.amount)}</span>
      </div>
      <div className="rv-name">{name}</div>
      <div className="sub">
        {meta}
        {item.installment && <span className="rv-badge">{item.installment}</span>}
      </div>

      {shown && (
        <div className="rv-suggest">
          <span className="mut">{item.suggestion ? t.review.suggestion : t.review.current}</span>{" "}
          <b>{shown.icon} {shown.label}</b>
          <div className="rv-reason">{item.suggestion ? item.suggestion.detail : t.review.currentDetail}</div>
        </div>
      )}

      <div className="rv-chips">
        <CategoryPicker direction={direction} value={selected} onChange={setSelected} top={chips} />
      </div>

      <label className="rv-switch">
        <input type="checkbox" role="switch" checked={rule} onChange={(e) => setRule(e.target.checked)} />
        <span className="rv-track" aria-hidden="true"><i /></span>
        {t.review.alwaysUse(shorten(name))}
      </label>

      <input
        className="rv-note"
        type="text"
        aria-label={t.review.note}
        placeholder={t.review.notePlaceholder}
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />

      <div className="rv-actions">
        <button type="button" className="rv-btn" disabled={busy} onClick={skip}>{t.review.skip}</button>
        <button type="submit" className="rv-btn primary" disabled={busy || !selected} aria-busy={busy}>
          {t.review.confirm}
        </button>
      </div>
    </form>
  );
}
