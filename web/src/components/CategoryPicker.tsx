import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useTaxonomy } from "../api/queries";
import { t } from "../i18n/pt-BR";
import "./category-picker.css";

export type Direction = "in" | "out";

/** P&L lines listed first per direction. The direction only orders the list, it never restricts it: refunds and
 *  people paying back their share go to expense categories, netting the expense. */
const FIRST_LINES: Record<Direction, string[]> = { in: ["income"], out: ["expenses", "commissions"] };
export const OWN_TRANSFER = "own_transfer";

/** Taxonomy lines with the direction's lines first, the others after in taxonomy order. */
export function orderLines<L extends { id: string }>(lines: L[], direction: Direction): L[] {
  const first = FIRST_LINES[direction];
  const rank = (id: string) => (first.includes(id) ? first.indexOf(id) : first.length);
  return lines.map((l, i) => ({ l, i })).sort((a, b) => rank(a.l.id) - rank(b.l.id) || a.i - b.i).map((x) => x.l);
}

/** Lowercase without accents: "Educação" -> "educacao". */
export function fold(s: string): string {
  return s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
}

interface CategoryPickerProps {
  /** Orders the "Outra" list (this direction's P&L lines first); every category stays available. */
  direction: Direction;
  value: string | null;
  onChange: (categoryId: string) => void;
  /** Chip ids, in order (keyboard 1–9 follow this order). The current value gets a chip of its own when missing. */
  top: string[];
}

export function CategoryPicker({ direction, value, onChange, top }: CategoryPickerProps) {
  const taxonomy = useTaxonomy();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const toggleRef = useRef<HTMLButtonElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const focusChip = useRef<string | null>(null);
  const listId = useId();
  const byId = useMemo(() => new Map(taxonomy.data?.categories.map((c) => [c.id, c]) ?? []), [taxonomy.data]);

  const chips = [...top, ...(value && !top.includes(value) ? [value] : [])].filter((id) => byId.has(id));
  const groups = useMemo(() => {
    const q = fold(query.trim());
    const cats = (taxonomy.data?.categories ?? []).filter((c) => !q || fold(c.label).includes(q));
    return orderLines(taxonomy.data?.lines ?? [], direction)
      .map((l) => ({ id: l.id, label: t.review.lines[l.id] ?? l.label, cats: cats.filter((c) => c.line === l.id) }))
      .filter((g) => g.cats.length > 0);
  }, [taxonomy.data, direction, query]);

  // After a pick from the list, focus moves to that category's chip (so Enter then confirms it).
  useEffect(() => {
    const id = focusChip.current;
    if (!id) return;
    focusChip.current = null;
    rootRef.current?.querySelector<HTMLButtonElement>(`[data-chip="${CSS.escape(id)}"]`)?.focus();
  });

  const pick = (id: string) => {
    focusChip.current = id;
    onChange(id);
    setOpen(false);
    setQuery("");
  };
  const onSearchKey = (ev: KeyboardEvent<HTMLInputElement>) => {
    if (ev.key === "Enter") {
      ev.preventDefault(); // inside a form: Enter picks the first match instead of submitting
      const first = groups[0]?.cats[0];
      if (first) pick(first.id);
    } else if (ev.key === "Escape") {
      ev.preventDefault();
      setOpen(false);
      toggleRef.current?.focus();
    }
  };

  return (
    <div className="cpick" ref={rootRef}>
      <div className="cpick-chips" role="group" aria-label={t.review.category}>
        {chips.map((id) => {
          const c = byId.get(id)!;
          return (
            <button
              key={id}
              type="button"
              data-chip={id}
              className={`chip${id === value ? " sel" : ""}`}
              aria-pressed={id === value}
              onClick={() => onChange(id)}
            >
              {c.icon} {c.label}
            </button>
          );
        })}
        <button
          ref={toggleRef}
          type="button"
          className="chip chip-more"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => setOpen((v) => !v)}
        >
          {t.review.other}
        </button>
      </div>
      {open && (
        <div className="cpick-panel" id={listId}>
          <input
            type="search"
            className="cpick-search"
            placeholder={t.review.searchCategory}
            aria-label={t.review.searchCategory}
            value={query}
            autoFocus
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onSearchKey}
          />
          <div className="cpick-list" role="listbox" aria-label={t.review.category}>
            {groups.length === 0 && <div className="cpick-none">{t.review.noMatch}</div>}
            {groups.map((g) => (
              <div key={g.id} role="group" aria-label={g.label}>
                <div className="cpick-line" aria-hidden="true">{g.label}</div>
                {g.cats.map((c) => (
                  <div
                    key={c.id}
                    role="option"
                    tabIndex={0}
                    aria-selected={c.id === value}
                    className="cpick-opt"
                    onClick={() => pick(c.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        e.stopPropagation();
                        pick(c.id);
                      }
                    }}
                  >
                    <span aria-hidden="true">{c.icon}</span> {c.label}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
