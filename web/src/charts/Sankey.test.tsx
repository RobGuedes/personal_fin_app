import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { COMPACT, COMPACT_NAME, Sankey, type SankeyData } from "./Sankey";

const node = (id: string, label: string, side: "source" | "middle" | "target", value: number, filter: Record<string, string> | null, extra = {}) => ({
  id, label, side, key: id.replace(/^(src|dst):/, "").replace(/^mid$/, "renda"), value, filter, ...extra,
});

const ok: SankeyData = {
  nodes: [
    node("src:dividends", "Dividendos", "source", 6000, { category: "dividends" }),
    node("src:services_nf", "Serviços (NF)", "source", 4000, { category: "services_nf" }),
    node("mid", "Renda", "middle", 10000, null, { income: 10000 }),
    node("dst:sobrou", "Sobrou", "target", 5000, null),
    node("dst:restaurants", "Restaurantes", "target", 3000, { category: "restaurants" }),
    node("dst:tax_provision", "Imposto (provisão)", "target", 2000, null),
  ],
  links: [
    { source: "src:dividends", target: "mid", value: 6000 },
    { source: "src:services_nf", target: "mid", value: 4000 },
    { source: "mid", target: "dst:sobrou", value: 5000 },
    { source: "mid", target: "dst:restaurants", value: 3000 },
    { source: "mid", target: "dst:tax_provision", value: 2000 },
  ],
};

const deficit: SankeyData = {
  nodes: [
    node("src:dividends", "Dividendos", "source", 6000, { category: "dividends" }),
    node("src:reservas_usadas", "Reservas usadas", "source", 2000, null),
    node("mid", "Renda", "middle", 8000, null, { income: 6000 }),
    node("dst:restaurants", "Restaurantes", "target", 8000, { category: "restaurants" }),
  ],
  links: [
    { source: "src:dividends", target: "mid", value: 6000 },
    { source: "src:reservas_usadas", target: "mid", value: 2000 },
    { source: "mid", target: "dst:restaurants", value: 8000 },
  ],
};

describe("Sankey", () => {
  it("new data while a link is hovered does not crash or keep a stale tooltip", () => {
    const { rerender } = render(<Sankey data={ok} />);
    fireEvent.mouseEnter(screen.getAllByTestId("sankey-link")[4]);
    expect(screen.getByTestId("sankey-tip")).toBeTruthy();
    rerender(<Sankey data={deficit} />); // 3 links: index 4 no longer exists
    expect(screen.getAllByTestId("sankey-link")).toHaveLength(3);
    expect(screen.queryByTestId("sankey-tip")).toBeNull();
  });

  it("new data while a node is hovered drops the old tooltip", () => {
    const { rerender } = render(<Sankey data={ok} />);
    fireEvent.mouseEnter(screen.getByLabelText("Serviços (NF): R$ 4.000,00 (40%)")); // node index 1
    expect(screen.getByTestId("sankey-tip").textContent).toContain("Serviços");
    rerender(<Sankey data={deficit} />); // index 1 is now "Reservas usadas": must not show it
    expect(screen.queryByTestId("sankey-tip")).toBeNull();
  });

  it("renders one node per data node", () => {
    render(<Sankey data={ok} />);
    expect(screen.getAllByTestId("sankey-node")).toHaveLength(6);
  });

  it("labels show name, value and % of renda; the middle shows Renda", () => {
    render(<Sankey data={ok} />);
    expect(screen.getByLabelText("Sobrou: R$ 5.000,00 (50%)")).toBeTruthy();
    expect(screen.getByLabelText("Restaurantes: R$ 3.000,00 (30%)")).toBeTruthy();
    expect(screen.getByLabelText("Renda: R$ 10.000,00")).toBeTruthy();
  });

  it("clicking a category node calls onNodeClick(key, filter); filterless nodes are not clickable", () => {
    const onNodeClick = vi.fn();
    render(<Sankey data={ok} onNodeClick={onNodeClick} />);
    fireEvent.click(screen.getByLabelText("Restaurantes: R$ 3.000,00 (30%)"));
    expect(onNodeClick).toHaveBeenCalledWith("restaurants", { category: "restaurants" });
    fireEvent.click(screen.getByLabelText("Sobrou: R$ 5.000,00 (50%)"));
    fireEvent.click(screen.getByLabelText("Imposto (provisão): R$ 2.000,00 (20%)"));
    expect(onNodeClick).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Sobrou: R$ 5.000,00 (50%)").getAttribute("tabindex")).toBeNull();
  });

  it("clickable nodes work from the keyboard", () => {
    const onNodeClick = vi.fn();
    render(<Sankey data={ok} onNodeClick={onNodeClick} />);
    const n = screen.getByLabelText("Restaurantes: R$ 3.000,00 (30%)");
    expect(n.getAttribute("tabindex")).toBe("0");
    fireEvent.keyDown(n, { key: "Enter" });
    fireEvent.keyDown(n, { key: " " });
    expect(onNodeClick).toHaveBeenCalledTimes(2);
  });

  it("deficit: Reservas usadas source; percentages and middle label follow renda (income), not the middle value", () => {
    render(<Sankey data={deficit} />);
    expect(screen.getByLabelText("Reservas usadas: R$ 2.000,00 (33%)")).toBeTruthy();
    expect(screen.getByLabelText("Restaurantes: R$ 8.000,00 (133%)")).toBeTruthy();
    expect(screen.getByLabelText("Renda: R$ 6.000,00")).toBeTruthy();
  });

  it("hovering a band shows its value", () => {
    render(<Sankey data={ok} />);
    fireEvent.mouseEnter(screen.getAllByTestId("sankey-link")[0]);
    expect(screen.getByTestId("sankey-tip").textContent).toContain("R$ 6.000,00");
  });

  it("has a text alternative listing every flow", () => {
    render(<Sankey data={ok} />);
    const rows = screen.getAllByRole("row", { hidden: true });
    expect(rows).toHaveLength(1 + ok.links.length);
    expect(rows[1].textContent).toContain("Dividendos");
  });

  it("compact: labels only for nodes >= 4% of renda, and a tap opens the full view", () => {
    const small: SankeyData = {
      nodes: [...ok.nodes.slice(0, 3), node("dst:sobrou", "Sobrou", "target", 9700, null), node("dst:tiny", "Miudeza", "target", 300, { category: "tiny" })],
      links: [...ok.links.slice(0, 2), { source: "mid", target: "dst:sobrou", value: 9700 }, { source: "mid", target: "dst:tiny", value: 300 }],
    };
    const onOpen = vi.fn();
    render(<Sankey data={small} compact onOpen={onOpen} />);
    expect(screen.queryByText("Miudeza", { selector: "tspan" })).toBeNull();
    expect(screen.getByText("Sobrou", { selector: "tspan" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button"));
    expect(onOpen).toHaveBeenCalled();
  });

  it("adjacent tiny nodes never get overlapping labels", () => {
    const tiny = Array.from({ length: 8 }, (_, i) => node(`dst:c${i}`, `Cat ${i}`, "target", 100, { category: `c${i}` }));
    const dense: SankeyData = {
      nodes: [node("src:a", "A", "source", 10000, { category: "a" }), node("mid", "Renda", "middle", 10000, null, { income: 10000 }),
        node("dst:big", "Grande", "target", 9200, { category: "big" }), ...tiny],
      links: [{ source: "src:a", target: "mid", value: 10000 }, { source: "mid", target: "dst:big", value: 9200 },
        ...tiny.map((n) => ({ source: "mid", target: n.id, value: 100 }))],
    };
    render(<Sankey data={dense} />);
    const ys = screen.getAllByTestId("sankey-label").filter((l) => l.getAttribute("text-anchor") === "start").map((l) => Number(l.getAttribute("y"))).sort((a, b) => a - b);
    expect(ys.length).toBeLessThan(10);
    for (let i = 1; i < ys.length; i++) expect(ys[i] - ys[i - 1]).toBeGreaterThanOrEqual(14);
    expect(screen.getAllByTestId("sankey-node")).toHaveLength(11); // hidden labels keep their nodes
  });

  it("hover then click keeps the tooltip (mouse)", () => {
    render(<Sankey data={ok} />);
    const band = screen.getAllByTestId("sankey-link")[0];
    fireEvent.pointerEnter(band, { pointerType: "mouse" });
    fireEvent.mouseEnter(band);
    fireEvent.pointerDown(band, { pointerType: "mouse" });
    fireEvent.click(band);
    expect(screen.getByTestId("sankey-tip")).toBeTruthy();
  });

  it("touch: the first tap shows the tooltip (despite the emulated mouseenter and click), the second clears it, a tap elsewhere clears it", () => {
    render(<Sankey data={ok} />);
    const band = screen.getAllByTestId("sankey-link")[0];
    const tap = () => {
      fireEvent.pointerEnter(band, { pointerType: "touch" });
      fireEvent.pointerDown(band, { pointerType: "touch" });
      fireEvent.mouseEnter(band);
      fireEvent.click(band);
    };
    tap();
    expect(screen.getByTestId("sankey-tip")).toBeTruthy();
    tap();
    expect(screen.queryByTestId("sankey-tip")).toBeNull();
    tap();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByTestId("sankey-tip")).toBeNull();
  });

  it("compact: unlabelled tiny nodes do not suppress a later visible label", () => {
    const d: SankeyData = {
      nodes: [node("src:a", "A", "source", 10000, null), node("mid", "Renda", "middle", 10000, null, { income: 10000 }),
        node("dst:t1", "Mini", "target", 100, null), node("dst:big", "Grande", "target", 9900, null)],
      links: [{ source: "src:a", target: "mid", value: 10000 }, { source: "mid", target: "dst:t1", value: 100 }, { source: "mid", target: "dst:big", value: 9900 }],
    };
    render(<Sankey data={d} compact />);
    expect(screen.getByText("Grande", { selector: "tspan" })).toBeTruthy();
    expect(screen.queryByText("Mini", { selector: "tspan" })).toBeNull();
  });
});

describe("Sankey text alternative", () => {
  it("keeps the table inside a .sr-only wrapper (tables ignore the 1px width themselves)", () => {
    const { container } = render(<Sankey data={ok} />);
    const table = container.querySelector("table");
    expect(table).toBeTruthy();
    expect(table!.parentElement!.classList.contains("sr-only")).toBe(true);
    expect(table!.classList.contains("sr-only")).toBe(false);
  });
});

describe("compact Sankey gutters", () => {
  it("reserve room for the longest label on both sides", () => {
    const need = 8 + (COMPACT_NAME + " 100%".length) * COMPACT.font * 0.6;
    expect(COMPACT.left).toBeGreaterThanOrEqual(need);
    expect(COMPACT.right).toBeGreaterThanOrEqual(need);
  });
});
