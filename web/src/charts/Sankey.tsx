import { sankey, sankeyLinkHorizontal } from "d3-sankey";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { components } from "../api/schema";
import type { Taxonomy } from "../api/queries";
import { categoryColor } from "../components/CategoryRow";
import { t } from "../i18n/pt-BR";
import { brl, brlCompact, pct } from "../lib/format";

export type SankeyData = components["schemas"]["SankeyOut"];
export type SankeyNode = components["schemas"]["SankeyNode"];
export type SankeyFilter = SankeyNode["filter"];

interface Props {
  data: SankeyData;
  /** viewBox height of the full chart (the width is fixed). */
  height?: number;
  /** Node `key` plus the transaction filter behind it. Only nodes with a filter are clickable. */
  onNodeClick?: (key: string, filter: NonNullable<SankeyFilter>) => void;
  /** Phone version: labels only for nodes >= 4% of renda; the whole chart is one button calling `onOpen`. */
  compact?: boolean;
  onOpen?: () => void;
  /** Taxonomy categories, for the fixed category colors; without them category nodes are gray. */
  categories?: Taxonomy["categories"];
}

const NODE_W = 12;
const PAD = 10;
const MIN_LABEL = 0.04; // compact: label nodes with at least this share of renda
const SOURCE_COLORS = ["var(--series-income)", "var(--accent)", "var(--flow-src-2)", "var(--flow-src-3)"];
const LINE_COLORS: Record<string, string> = {
  commissions: "var(--split-outros)",
  tax_provision: "var(--split-outros)",
  sobrou: "var(--positive)",
};
const GRAY = "var(--cat-other)";

const FULL = { w: 980, left: 215, right: 215, top: 30, bottom: 8, font: 13, small: 12 };
/** Longest compact name; the gutters reserve (COMPACT_NAME + " 100%") characters at ~0.6em each plus the 8px node gap. */
export const COMPACT_NAME = 8;
export const COMPACT = { w: 360, left: 90, right: 90, top: 22, bottom: 6, font: 10.5, small: 10 };

type Laid = SankeyNode & { x0: number; x1: number; y0: number; y1: number; index: number };
type LaidLink = { source: Laid; target: Laid; value: number; width: number; y0: number; y1: number; index: number };

function truncate(s: string, n: number) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

export function Sankey({ data, height, onNodeClick, compact = false, onOpen, categories }: Props) {
  // Hover/focus target, tied to the layout it indexes: new data (another period) drops it instead of
  // reading a link/node index that no longer exists (crash) or now points at another band (wrong tooltip).
  type Active = { kind: "node" | "link"; i: number };
  const [hover, setHover] = useState<(Active & { of: unknown }) | null>(null);
  // Last pointer type seen on a band: touch/pen browsers emit an emulated mouseenter (and a click) after the tap.
  const pointer = useRef<string | null>(null);
  const touchy = () => pointer.current === "touch" || pointer.current === "pen";
  const dim = compact ? COMPACT : FULL;
  const H = height ?? (compact ? 280 : 440);
  const middle = data.nodes.find((n) => n.side === "middle");
  const renda = middle?.income ?? middle?.value ?? 0;
  const share = (v: number) => (renda > 0 ? v / renda : 0);

  const layout = useMemo(() => {
    if (data.nodes.length === 0 || data.links.length === 0) return null;
    const gen = sankey()
      .nodeId((d: SankeyNode) => d.id)
      .nodeWidth(NODE_W)
      .nodePadding(compact ? 6 : PAD)
      .nodeSort(null)
      .linkSort(null)
      .extent([[dim.left, dim.top], [dim.w - dim.right, H - dim.bottom]]);
    return gen({ nodes: data.nodes.map((n) => ({ ...n })), links: data.links.map((l) => ({ ...l })) }) as {
      nodes: Laid[];
      links: LaidLink[];
    };
  }, [data, compact, H, dim.left, dim.right, dim.top, dim.bottom, dim.w]);
  const active: Active | null = hover && hover.of === layout ? hover : null;
  const setActive = useCallback(
    (next: Active | null | ((a: Active | null) => Active | null)) =>
      setHover((h) => {
        const prev = h && h.of === layout ? h : null;
        const value = typeof next === "function" ? next(prev) : next;
        return value ? { ...value, of: layout } : null;
      }),
    [layout],
  );

  // Touch: a tap outside the chart dismisses the tooltip (mouse leave handles the pointer case).
  useEffect(() => {
    if (!active) return;
    const away = (e: Event) => {
      if (!(e.target as Element | null)?.closest?.(".sankey-svg")) setActive(null);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [active, setActive]);

  if (!layout || !middle) return <p className="empty sankey-empty">{t.sankey.empty}</p>;

  const byId = new Map((categories ?? []).map((c) => [c.id, c]));
  let srcIdx = 0;
  const colors = new Map<string, string>();
  for (const n of layout.nodes) {
    let c: string;
    if (n.side === "middle") c = "var(--muted)";
    else if (n.key in LINE_COLORS) c = LINE_COLORS[n.key];
    else if (n.key === "outras_rendas" || n.key === "outras_despesas" || n.key === "reservas_usadas") c = GRAY;
    else if (n.key.startsWith("uncategorized:") || n.key.startsWith("manual:")) c = GRAY;
    else if (n.side === "source") c = SOURCE_COLORS[srcIdx++ % SOURCE_COLORS.length];
    else c = categoryColor(byId.get(n.key));
    colors.set(n.id, c);
  }
  const outer = (l: LaidLink) => (l.source.side === "middle" ? l.target : l.source);
  const linkPath = sankeyLinkHorizontal();

  const nodeLabel = (n: SankeyNode) =>
    n.side === "middle" ? t.sankey.middle(t.sankey.renda, brl(renda)) : t.sankey.node(n.label, brl(n.value), pct(share(n.value)));

  const isOn = (kind: "node" | "link", i: number) => active?.kind === kind && active.i === i;
  const related = (n: Laid) =>
    active?.kind === "link" && (layout.links[active.i].source.id === n.id || layout.links[active.i].target.id === n.id);
  const dimNode = (n: Laid) => active !== null && !isOn("node", n.index) && !related(n);
  const dimLink = (l: LaidLink) =>
    active !== null &&
    !isOn("link", l.index) &&
    !(active.kind === "node" && (l.source.index === active.i || l.target.index === active.i));

  const tipLink = active?.kind === "link" ? layout.links[active.i] : null;
  const tipNode = active?.kind === "node" ? layout.nodes[active.i] : null;
  const tip = tipLink
    ? {
        x: (tipLink.source.x1 + tipLink.target.x0) / 2,
        y: (tipLink.y0 + tipLink.y1) / 2,
        title: `${tipLink.source.label} → ${tipLink.target.label}`,
        value: tipLink.value,
        color: colors.get(outer(tipLink).id) ?? GRAY,
      }
    : tipNode
      ? {
          x: (tipNode.x0 + tipNode.x1) / 2,
          y: (tipNode.y0 + tipNode.y1) / 2,
          title: tipNode.side === "middle" ? t.sankey.renda : tipNode.label,
          value: tipNode.side === "middle" ? renda : tipNode.value,
          color: colors.get(tipNode.id) ?? GRAY,
        }
      : null;

  // Label placement per side, top to bottom: a label too close to the previous visible one drops to one line,
  // then to nothing (the aria-label, tooltip and the sr-only table still carry it).
  const placement = new Map<string, "two" | "one" | "none">();
  for (const side of ["source", "target"] as const) {
    let prev: { cy: number; two: boolean } | null = null;
    for (const n of layout.nodes.filter((x) => x.side === side).sort((a, b) => a.y0 - b.y0)) {
      const cy = (n.y0 + n.y1) / 2;
      if (compact && share(n.value) < MIN_LABEL) {
        placement.set(n.id, "none"); // its label is never drawn, so it must not push a visible one away
        continue;
      }
      const wantTwo = n.y1 - n.y0 >= (compact ? 22 : 30);
      const gap = (two: boolean) => (prev ? (prev.two ? (two ? 2.4 : 1.7) : two ? 1.7 : 1) : 0) * (compact ? 12 : 14);
      const fits = (two: boolean) => !prev || cy - prev.cy >= gap(two);
      const mode = wantTwo && fits(true) ? "two" : fits(false) ? "one" : "none";
      placement.set(n.id, mode);
      if (mode !== "none") prev = { cy, two: mode === "two" };
    }
  }

  const press = (n: Laid) => {
    if (n.filter) onNodeClick?.(n.key, n.filter);
  };
  const onKey = (n: Laid) => (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      press(n);
    }
  };

  const svg = (
    <svg
      viewBox={`0 0 ${dim.w} ${H}`}
      className="sankey-svg"
      role="group"
      aria-label={t.sankey.chart}
      onMouseLeave={() => setActive(null)}
    >
      <g>
        {layout.links.map((l) => (
          <path
            key={l.index}
            data-testid="sankey-link"
            d={linkPath(l) ?? ""}
            fill="none"
            stroke={colors.get(outer(l).id)}
            strokeWidth={Math.max(1, l.width - 2)}
            className={`sankey-link${dimLink(l) ? " is-dim" : ""}`}
            aria-hidden="true"
            onPointerEnter={(e: PointerEvent) => { pointer.current = e.pointerType; }}
            onPointerDown={(e: PointerEvent) => {
              pointer.current = e.pointerType;
              // Touch/pen: the tap toggles; mouse: hover owns the tooltip.
              if (touchy()) setActive((a) => (a?.kind === "link" && a.i === l.index ? null : { kind: "link", i: l.index }));
            }}
            onMouseEnter={() => { if (!touchy()) setActive({ kind: "link", i: l.index }); }}
            onClick={() => { if (pointer.current === null) setActive({ kind: "link", i: l.index }); }}
          />
        ))}
      </g>
      {layout.nodes.map((n) => {
        const h = n.y1 - n.y0;
        const clickable = !compact && !!n.filter && !!onNodeClick;
        const isMid = n.side === "middle";
        const frac = share(n.value);
        const mode = placement.get(n.id);
        const labelled = (!compact || isMid || frac >= MIN_LABEL) && (isMid || mode !== "none");
        const left = n.side === "source";
        const lx = isMid ? (n.x0 + n.x1) / 2 : left ? n.x0 - 8 : n.x1 + 8;
        const anchor = isMid ? "middle" : left ? "end" : "start";
        const cy = (n.y0 + n.y1) / 2;
        const two = mode === "two";
        const name = compact ? truncate(n.label, COMPACT_NAME) : n.label;
        const detail = compact ? pct(frac) : `${brlCompact(n.value)} · ${pct(frac)}`;
        return (
          <g
            key={n.id}
            data-testid="sankey-node"
            className={`sankey-node${dimNode(n) ? " is-dim" : ""}${clickable ? " is-clickable" : ""}`}
            role={clickable ? "button" : "img"}
            aria-label={nodeLabel(n)}
            tabIndex={clickable ? 0 : undefined}
            onMouseEnter={() => setActive({ kind: "node", i: n.index })}
            onFocus={() => setActive({ kind: "node", i: n.index })}
            onBlur={() => setActive(null)}
            onClick={clickable ? () => press(n) : undefined}
            onKeyDown={clickable ? onKey(n) : undefined}
          >
            <rect x={n.x0} y={n.y0} width={NODE_W} height={Math.max(h, 1)} rx={3} fill={colors.get(n.id)} />
            {/* Wider invisible target: the 12px bar alone is hard to hit. */}
            <rect x={n.x0 - 6} y={n.y0} width={NODE_W + 12} height={Math.max(h, 1)} fill="transparent" />
            {labelled &&
              (isMid ? (
                <text x={lx} y={n.y0 - 9} textAnchor="middle" className="sankey-name is-mid" fontSize={dim.font} aria-hidden="true">
                  {t.sankey.renda} {compact ? brlCompact(renda) : brl(renda)}
                </text>
              ) : two ? (
                <text data-testid="sankey-label" x={lx} y={cy - 2} textAnchor={anchor} fontSize={dim.font} aria-hidden="true">
                  <tspan className="sankey-name">{name}</tspan>
                  <tspan className="sankey-detail" x={lx} dy={dim.font + 3} fontSize={dim.small}>{detail}</tspan>
                </text>
              ) : (
                <text data-testid="sankey-label" x={lx} y={cy} dominantBaseline="central" textAnchor={anchor} fontSize={dim.font} aria-hidden="true">
                  <tspan className="sankey-name">{name}</tspan>
                  <tspan className="sankey-detail" fontSize={dim.small}>{` ${detail}`}</tspan>
                </text>
              ))}
          </g>
        );
      })}
    </svg>
  );

  const table = (
    <div className="sr-only">
    <table>
      <caption>{t.sankey.table}</caption>
      <thead>
        <tr><th>{t.sankey.from}</th><th>{t.sankey.to}</th><th>{t.sankey.value}</th></tr>
      </thead>
      <tbody>
        {data.links.map((l, i) => {
          const s = data.nodes.find((n) => n.id === l.source);
          const d = data.nodes.find((n) => n.id === l.target);
          return (
            <tr key={i}>
              <td>{s?.side === "middle" ? t.sankey.renda : s?.label}</td>
              <td>{d?.side === "middle" ? t.sankey.renda : d?.label}</td>
              <td>{brl(l.value)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
    </div>
  );

  if (compact) {
    return (
      <div className="sankey is-compact">
        <button type="button" className="sankey-open" aria-label={t.sankey.openFull} onClick={onOpen}>
          {svg}
        </button>
        {table}
      </div>
    );
  }
  return (
    <div className="sankey">
      <div className="sankey-plot" onMouseLeave={() => setActive(null)}>
        {svg}
        {tip && (
          <div
            className="tooltip sankey-tip"
            data-testid="sankey-tip"
            aria-hidden="true"
            style={{ left: `${(tip.x / dim.w) * 100}%`, top: `${(tip.y / H) * 100}%` }}
          >
            <strong>{tip.title}</strong>
            <span>
              <i style={{ background: tip.color }} aria-hidden="true" />
              {brl(tip.value)}
              {tip.title !== t.sankey.renda && renda > 0 ? ` · ${pct(share(tip.value))}` : ""}
            </span>
          </div>
        )}
      </div>
      {table}
    </div>
  );
}
