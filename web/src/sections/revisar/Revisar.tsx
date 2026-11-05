import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { api } from "../../api/client";
import { invalidateAfterMutation, useTaxonomy } from "../../api/queries";
import type { components } from "../../api/schema";
import { categoryName } from "../../components/CategoryRow";
import { Skeleton } from "../../components/Skeleton";
import { useToast } from "../../components/Toast";
import { t } from "../../i18n/pt-BR";
import { isTextEntry, ReviewCard, type ConfirmInput, type ReviewItem } from "./ReviewCard";
import "./revisar.css";

type ConfirmOut = components["schemas"]["ConfirmOut"];
type Previous = ConfirmOut["previous"];
interface Done {
  key: number; // one per confirmation: undo consumes it once
  id: string;
  item: ReviewItem; // shown again right after undo, before the refetch brings it back
  previous: Previous;
  ruleId: string | null;
  toastId?: number;
}
interface Restored {
  item: ReviewItem;
  at: number; // used until a review fetch newer than the undo arrives
}

const errorText = (e: unknown) => (e instanceof Error ? e.message : t.genericError);

export function Revisar() {
  const qc = useQueryClient();
  const toast = useToast();
  const review = useQuery({ queryKey: ["review"], queryFn: () => api<ReviewItem[]>("/review") });
  const taxonomy = useTaxonomy();

  // This visit's progress: confirmed entries (with what undo restores) and skipped ids. The inbox is refetched after
  // every mutation; ids handled here are hidden even before the refetch lands, so the next card shows at once.
  const [done, setDone] = useState<Done[]>([]);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [restored, setRestored] = useState<Restored[]>([]);
  const [pinned, setPinned] = useState<string | null>(null); // a card brought back by undo shows first
  const inFlight = useRef(false); // confirm or undo running: a second press before the re-render is ignored
  const consumed = useRef(new Set<number>()); // Done keys already undone (or being undone)
  const nextKey = useRef(1);

  const label = (id: string) => categoryName(id, taxonomy.data?.categories.find((c) => c.id === id));

  const undo = useMutation({
    mutationFn: (d: Done) => api<unknown>(`/review/${encodeURIComponent(d.id)}/undo`, { method: "POST", body: JSON.stringify({ previous: d.previous }) }),
    onSuccess: (_r, d) => {
      setDone((xs) => xs.filter((x) => x.key !== d.key));
      setSkipped((xs) => xs.filter((x) => x !== d.id));
      setRestored((xs) => [...xs.filter((x) => x.item.id !== d.id), { item: d.item, at: Date.now() }]);
      setPinned(d.id);
      toast.show(d.ruleId ? `${t.review.undone} · ${t.review.ruleStays}` : t.review.undone);
    },
    onError: (e, d) => {
      consumed.current.delete(d.key); // still in `done`: U can retry
      toast.show(errorText(e));
    },
    onSettled: () => {
      inFlight.current = false;
      void invalidateAfterMutation(qc);
    },
  });

  const undoEntry = useCallback(
    (d: Done) => {
      if (inFlight.current || consumed.current.has(d.key)) return;
      inFlight.current = true;
      consumed.current.add(d.key);
      if (d.toastId !== undefined) toast.dismiss(d.toastId);
      undo.mutate(d);
    },
    [undo, toast],
  );
  const undoRef = useRef(undoEntry);
  undoRef.current = undoEntry;

  const confirm = useMutation({
    mutationFn: ({ item, input }: { item: ReviewItem; input: ConfirmInput }) =>
      api<ConfirmOut>(`/review/${encodeURIComponent(item.id)}/confirm`, { method: "POST", body: JSON.stringify(input) }),
    onSuccess: (res, { item, input }) => {
      const entry: Done = { key: nextKey.current++, id: item.id, item, previous: res.previous, ruleId: res.rule_id };
      setDone((xs) => [...xs, entry]);
      setRestored((xs) => xs.filter((x) => x.item.id !== item.id));
      setPinned((p) => (p === item.id ? null : p));
      const msg = t.review.classifiedAs(label(input.category_id));
      entry.toastId = toast.show(res.rule_id ? `${msg} · ${t.review.ruleCreated}` : msg, {
        action: { label: t.undo, onClick: () => undoRef.current(entry) },
      });
      void invalidateAfterMutation(qc);
    },
    onError: (e) => toast.show(errorText(e)), // e.g. 422 "Não foi possível criar uma regra…": nothing was saved
    onSettled: () => {
      inFlight.current = false;
    },
  });

  const busy = confirm.isPending || undo.isPending;

  const onConfirm = (item: ReviewItem, input: ConfirmInput) => {
    if (inFlight.current) return;
    inFlight.current = true;
    confirm.mutate({ item, input });
  };
  const onSkip = (id: string) => {
    if (inFlight.current) return; // skipping during a confirm would count the card twice
    setPinned((p) => (p === id ? null : p));
    setSkipped((xs) => [...xs, id]);
  };

  // U undoes the latest confirmation of this visit (also after the last card).
  const lastDone = done[done.length - 1];
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.metaKey || ev.ctrlKey || ev.altKey || isTextEntry(ev.target)) return;
      if ((ev.key === "u" || ev.key === "U") && lastDone) {
        ev.preventDefault();
        undoRef.current(lastDone);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lastDone]);

  const header = (progress?: { i: number; n: number }) => (
    <header className="rv-head">
      <h1>{t.review.title}</h1>
      {progress && <span className="sub">{t.review.progress(progress.i, progress.n)}</span>}
    </header>
  );

  if (review.isError || taxonomy.isError) {
    return (
      <section className="revisar">
        {header()}
        <div className="card empty" role="alert">{errorText(review.error ?? taxonomy.error)}</div>
      </section>
    );
  }
  if (!review.data || !taxonomy.data) {
    return (
      <section className="revisar" aria-busy="true">
        {header()}
        <Skeleton height={6} />
        <Skeleton height={380} />
      </section>
    );
  }

  const doneIds = new Set(done.map((d) => d.id));
  const skippedIds = new Set(skipped);
  const server = review.data;
  const serverIds = new Set(server.map((x) => x.id));
  const local = restored.filter((r) => !serverIds.has(r.item.id) && review.dataUpdatedAt < r.at).map((r) => r.item);
  const remaining = [...server, ...local].filter((x) => !doneIds.has(x.id) && !skippedIds.has(x.id));
  const item = remaining.find((x) => x.id === pinned) ?? remaining[0];
  const handled = done.length + skipped.length;
  const total = handled + remaining.length;

  if (!item) {
    return (
      <section className="revisar">
        {header()}
        {skipped.length > 0 ? (
          <div className="card empty rv-empty">
            <strong>{t.review.skippedAll(skipped.length)}</strong>
            <p>{t.review.skippedHint}</p>
            <button type="button" className="rv-btn primary rv-again" onClick={() => setSkipped([])}>
              {t.review.reviewSkipped}
            </button>
          </div>
        ) : (
          <div className="card empty rv-empty">
            <strong>{t.review.empty}</strong>
            <p>{t.review.emptyHint}</p>
            <Link to="/" className="link-btn">{t.review.backHome}</Link>
          </div>
        )}
      </section>
    );
  }

  return (
    <section className="revisar">
      {header({ i: handled + 1, n: total })}
      <div
        className="rv-progress"
        role="progressbar"
        aria-label={t.review.progressLabel}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={handled}
      >
        <b style={{ width: `${(handled / total) * 100}%` }} />
      </div>
      <ReviewCard
        key={item.id}
        item={item}
        busy={busy}
        onConfirm={(input) => onConfirm(item, input)}
        onSkip={() => onSkip(item.id)}
      />
      <p className="rv-hint">{t.review.hint}</p>
    </section>
  );
}
