import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { Patrimonio } from "./Patrimonio";

const networth = {
  total: 1000000,
  as_of: "2026-10-31",
  groups: [
    { grp: "investments", label: "Investimentos", value: 900000, accounts: [{ label: "XP Fundos", value: 900000, updated_at: "2026-10-30T12:00:00Z" }] },
    { grp: "accounts", label: "Contas", value: 40000, accounts: [{ label: "Itaú Corrente", value: 40000, updated_at: null }] },
    { grp: "crypto", label: "Cripto", value: 90000, accounts: [{ label: "Binance", value: 90000, updated_at: "2026-10-31T08:00:00Z" }] },
    { grp: "cards", label: "Cartões", value: -30000, accounts: [{ label: "Cartão Visa", value: -30000, updated_at: "2026-10-31T08:00:00Z" }] },
  ],
};
const history = [
  { date: "2026-09-15", accounts: 1, investments: 1, crypto: 1, cards: -1, total: 800000 },
  { date: "2026-09-16", accounts: 1, investments: 1, crypto: 1, cards: -1, total: 850000 },
  { date: "2026-10-31", accounts: 1, investments: 1, crypto: 1, cards: -1, total: 1000000 },
];
const contributions = { months: ["2026-09", "2026-10"], values: { "2026-09": 1000, "2026-10": 2500 }, total: 3500 };

function setup(opts: { history?: unknown; month?: unknown; networth?: unknown; contributions?: unknown } = {}) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url.includes("/summary/month")) {
      return opts.month === "error"
        ? new Response(JSON.stringify({ error: "Falhou", code: "x" }), { status: 500 })
        : new Response(JSON.stringify({ month: "2026-10" }), { status: 200 });
    }
    const body = url.includes("/networth/history") ? (opts.history ?? history) : url.includes("/networth/contributions") ? (opts.contributions ?? contributions) : (opts.networth ?? networth);
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Patrimonio /></MemoryRouter>
    </QueryClientProvider>,
  );
  return fetchMock;
}

describe("Patrimônio", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("shows the total, the change since the first snapshot and the four groups", async () => {
    setup();
    expect((await screen.findAllByText("R$ 1.000.000,00")).length).toBeGreaterThan(0);
    expect(document.querySelector(".nw-total")?.textContent).toBe("R$ 1.000.000,00");
    expect(screen.getByText(/desde 15\/09/)).toBeTruthy();
    expect(screen.getByText(/\+ R\$ 200\.000,00/)).toBeTruthy();
    for (const g of ["Investimentos", "Contas", "Cripto", "Cartões"]) {
      expect(screen.getByRole("button", { name: new RegExp(g) })).toBeTruthy();
    }
  });

  it("shows Cartões negative in the warning color and expands a group to its accounts", async () => {
    setup();
    const cards = await screen.findByRole("button", { name: /Cartões/ });
    const value = within(cards).getByText("−R$ 30.000,00");
    expect(value.className).toContain("is-neg");
    expect(screen.queryByText("Cartão Visa")).toBeNull();
    await userEvent.click(cards);
    expect(cards.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Cartão Visa")).toBeTruthy();
    expect(screen.getByText(/atualizado 31\/10\/2026/)).toBeTruthy();
  });

  it("renders accounts sharing a label (Itaú CDBs) without a duplicate React key", async () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const dup = { label: "Itaú CDB", value: 1000, updated_at: null };
    setup({ networth: { ...networth, groups: [{ grp: "investments", label: "Investimentos", value: 2000, accounts: [dup, { ...dup }] }] } });
    await userEvent.click(await screen.findByRole("button", { name: /Investimentos/ }));
    expect(screen.getAllByText("Itaú CDB")).toHaveLength(2);
    expect(errors.mock.calls.flat().join(" ")).not.toMatch(/same key/);
    errors.mockRestore();
  });

  it("shows the empty-history state with fewer than two points", async () => {
    setup({ history: [history[0]] });
    expect(await screen.findByText("O histórico começa na próxima sincronização")).toBeTruthy();
    expect(screen.queryByTestId("area-chart")).toBeNull();
    expect(screen.queryByText(/desde/)).toBeNull();
  });

  it("shows a per-day tooltip on hover", async () => {
    setup();
    await screen.findByTestId("area-chart");
    const hits = screen.getAllByTestId("area-hit");
    expect(hits.length).toBe(3);
    fireEvent.mouseEnter(hits[1]);
    const tip = await screen.findByRole("status");
    expect(tip.textContent).toContain("16/09/2026");
    expect(tip.textContent).toContain("R$ 850.000,00");
  });

  it("asks for contributions of the server's current year and shows the total", async () => {
    const f = setup();
    expect(await screen.findByText("R$ 3.500,00")).toBeTruthy();
    expect(f.mock.calls.map((c) => String(c[0])).some((u) => u.includes("/networth/contributions?period=year%3A2026"))).toBe(true);
    expect(screen.getByText("2026")).toBeTruthy();
  });

  it("draws contributions as diverging bars: blue up, red down, a k label on each, 0 for a flat month", async () => {
    const mixed = { months: ["2026-06", "2026-07", "2026-08"], values: { "2026-06": 28400, "2026-07": -6200, "2026-08": -0.0 }, total: 22200 };
    setup({ contributions: mixed });
    const chart = await screen.findByTestId("contrib-chart");
    const cols = within(chart).getAllByTestId("contrib-hit");
    expect(cols).toHaveLength(3);
    const bar = (i: number) => cols[i].querySelector("i");
    expect(bar(0)?.className).not.toContain("is-neg");
    expect(bar(1)?.className).toContain("is-neg");
    expect(bar(2)).toBeNull();
    expect(cols.map((c) => c.textContent)).toEqual(["+28,4k", "−6,2k", "0"]);
    // up 28.4k + down 6.2k: baseline at 28.4 / 34.6 of the height; the red bar hangs from it
    const zero = (28400 / 34600) * 100;
    expect(chart.querySelector<HTMLElement>(".cbars-zero")?.style.top).toBe(`${zero}%`);
    expect(bar(1)?.style.top).toBe(`${zero}%`);
    expect(bar(0)?.style.bottom).toBe(`${100 - zero}%`);
    expect(cols[1].getAttribute("aria-label")).toMatch(/: −R\$ 6\.200,00$/);
  });

  it("highlights the server's current month, like Início", async () => {
    setup();
    const cols = await screen.findAllByTestId("contrib-hit");
    expect(cols.map((c) => c.classList.contains("on"))).toEqual([false, true]);
    expect(document.querySelector(".cbars-x .on")?.textContent).toBe("out");
  });

  it("shows the exact contribution in a tooltip on hover and on keyboard focus", async () => {
    const mixed = { months: ["2026-06", "2026-07"], values: { "2026-06": 28400, "2026-07": -8765.43 }, total: 19634.57 };
    setup({ contributions: mixed });
    const cols = await screen.findAllByTestId("contrib-hit");
    fireEvent.mouseEnter(cols[1]);
    const tip = await screen.findByRole("status");
    expect(tip.textContent).toContain("Resgatado −R$ 8.765,43");
    fireEvent.focus(cols[0]);
    expect(screen.getByRole("status").textContent).toContain("Aportado R$ 28.400,00");
  });

  it("keeps an sr-only table with every month's exact value", async () => {
    const mixed = { months: ["2026-06", "2026-07"], values: { "2026-06": 28400, "2026-07": -8765.43 }, total: 19634.57 };
    setup({ contributions: mixed });
    const table = (await screen.findByRole("table", { name: "Aportes por mês" }));
    expect(table.closest(".sr-only")).toBeTruthy();
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("−R$ 8.765,43")).toBeTruthy();
  });

  it("shows an error, not endless skeletons, when the current month fails", async () => {
    setup({ month: "error" });
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  });
});
