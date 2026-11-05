import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { ToastProvider } from "../../components/Toast";
import { Transacoes } from "../transacoes/Transacoes";
import { CategoryPage } from "./CategoryPage";
import { Panorama } from "./Panorama";

const months = ["2026-09", "2026-10"];
const taxonomy = {
  lines: [],
  categories: [
    { id: "housing", line: "expenses", label: "Moradia", icon: "🏠", color_slot: 1 },
    { id: "donations", line: "expenses", label: "Doações", icon: "💝", color_slot: 3 },
  ],
};
const panorama = {
  months, savings_rate: 0.45, avg_income: 55600, avg_spending: 30000,
  categories: [
    { category_id: "housing", label: "Moradia", total: 44400, monthly_avg: 3700, sparkline: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], usual: 3500 },
  ],
};
const pnl = {
  months,
  rows: [
    { key: "income", label: "Renda", level: 0, line: "income", values: { "2026-09": 50000, "2026-10": 54900 }, total: 104900, average: 52450 },
    { key: "expenses", label: "Despesas", level: 0, line: "expenses", values: { "2026-09": -20000, "2026-10": -24150 }, total: -44150, average: -22075 },
    { key: "housing", label: "Moradia", level: 1, line: "expenses", values: { "2026-09": -3000, "2026-10": -6150 }, total: -9150, average: -4575 },
  ],
};
const sankey = {
  nodes: [
    { id: "src:a", label: "Dividendos", side: "source", key: "dividends", value: 600, filter: { category: "dividends" } },
    { id: "mid", label: "Renda", side: "middle", key: "renda", value: 600, filter: null, income: 600 },
    { id: "dst:b", label: "Sobrou", side: "target", key: "sobrou", value: 600, filter: null },
  ],
  links: [{ source: "src:a", target: "mid", value: 600 }, { source: "mid", target: "dst:b", value: 600 }],
};
const channels = {
  months,
  totals: { "2026-09": 600, "2026-10": 600 },
  channels: [
    { method: "pix", label: "Pix", values: { "2026-09": 100, "2026-10": 200 }, total: 300 },
    { method: "card", label: "Cartão de crédito", values: { "2026-09": 500, "2026-10": 400 }, total: 900 },
  ],
};
const counterparties = { months, counterparties: [{ name: "Padaria Exemplo", total: 1234.5, count: 7 }] };
const categoryBody = {
  category_id: "housing", label: "Moradia",
  monthly: [{ month: "2026-08", value: 100 }, { month: "2026-09", value: 300 }, { month: "2026-10", value: 200 }],
  total: 600, usual: 250, budget: 400, top_counterparties: [{ name: "Locadora X", total: 900, count: 3 }],
};

function setup(path = "/panorama") {
  const fetchMock = vi.fn(async (url: string) => {
    const body = url.includes("/summary/month") ? { month: "2026-10" } : url.includes("/panorama?") ? panorama : url.includes("/sankey") ? sankey : url.includes("/pnl") ? pnl
      : url.includes("/channels") ? channels : url.includes("/counterparties") ? counterparties
      : url.includes("/categories/") ? categoryBody : taxonomy;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/panorama" element={<Panorama />} />
          <Route path="/panorama/categoria/:id" element={<CategoryPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetchMock;
}
const urls = (f: ReturnType<typeof setup>) => f.mock.calls.map((c) => String(c[0]));

describe("Panorama", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("defaults to 12 meses and refetches with the right period on switch (month comes from the server)", async () => {
    const f = setup();
    await screen.findByText("R$ 55,6 mil");
    expect(urls(f).some((u) => u.includes("/panorama?period=last12"))).toBe(true);
    await userEvent.click(screen.getByRole("tab", { name: "Mês" }));
    await waitFor(() => expect(urls(f).some((u) => u.includes("/panorama?period=month%3A2026-10"))).toBe(true));
    await userEvent.click(screen.getByRole("tab", { name: "Ano" }));
    await waitFor(() => expect(urls(f).some((u) => u.includes("/sankey?period=year%3A2026"))).toBe(true));
  });

  it("a browser clock ahead of São Paulo never leaks into the period", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2027-01-01T02:00:00Z") });
    try {
      const f = setup("/panorama?periodo=mes");
      await waitFor(() => expect(urls(f).some((u) => u.includes("/panorama?period=month%3A2026-10"))).toBe(true));
      expect(urls(f).some((u) => u.includes("2027"))).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("category page links into Transações with the month in Mês and all months otherwise", async () => {
    setup("/panorama/categoria/housing?periodo=mes");
    const link = await screen.findByRole("link", { name: "Ver transações" });
    expect(link.getAttribute("href")).toBe("/transacoes?mes=2026-10&categoria=housing&linha=expenses");
    cleanup();
    setup("/panorama/categoria/housing?periodo=ano");
    expect((await screen.findByRole("link", { name: "Ver transações" })).getAttribute("href")).toBe("/transacoes?mes=todos&categoria=housing&linha=expenses");
  });

  it("phone: the compact Sankey is one button that opens /panorama?fluxo=1", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: true, media: q, addEventListener: () => {}, removeEventListener: () => {} }));
    setup();
    await userEvent.click(await screen.findByRole("button", { name: "Abrir o fluxo completo" }));
    expect(await screen.findByRole("button", { name: "Fechar fluxo" })).toBeTruthy();
  });

  it("shows the KPI tiles", async () => {
    setup();
    expect(await screen.findByText("45%")).toBeTruthy();
    expect(screen.getByText("Taxa de poupança")).toBeTruthy();
    expect(screen.getByText("R$ 30 mil")).toBeTruthy();
  });

  it("category rows link to the category page and carry the period", async () => {
    setup();
    const link = await screen.findByRole("link", { name: /Moradia/ });
    expect(link.getAttribute("href")).toBe("/panorama/categoria/housing?periodo=12m");
    expect(within(link).getByText("R$ 3,7 mil/mês")).toBeTruthy();
  });

  it("Demonstrativo expands a line and links a category cell to Transações by month and category", async () => {
    setup();
    await userEvent.click(await screen.findByRole("tab", { name: "Demonstrativo" }));
    expect(screen.queryByText("Moradia", { selector: "th *, th" })).toBeNull();
    await userEvent.click(await screen.findByRole("button", { name: "Mostrar categorias de Despesas" }));
    const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(links).toContain("/transacoes?mes=2026-10&categoria=housing&linha=expenses");
    expect(links).toContain("/transacoes?mes=2026-09&categoria=housing&linha=expenses");
  });

  it("Canais lists the methods and Quem recebe the counterparties", async () => {
    setup();
    await userEvent.click(await screen.findByRole("tab", { name: "Canais" }));
    expect((await screen.findAllByText("Cartão de crédito")).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("tab", { name: "Quem recebe" }));
    expect(await screen.findByText("Padaria Exemplo")).toBeTruthy();
  });

  it("?fluxo=1 shows the full Sankey with a close control", async () => {
    setup("/panorama?fluxo=1");
    expect(await screen.findByRole("button", { name: "Fechar fluxo" })).toBeTruthy();
    expect(screen.queryByText("Taxa de poupança")).toBeNull();
  });
});

describe("CategoryPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders monthly bars, usual and budget lines, counterparties and a Transações link", async () => {
    const f = setup("/panorama/categoria/housing?periodo=12m");
    expect(await screen.findAllByTestId("cat-bar")).toHaveLength(3);
    expect(urls(f).some((u) => u.includes("/categories/housing?period=last12"))).toBe(true);
    expect(screen.getByTestId("usual-line")).toBeTruthy();
    expect(screen.getByTestId("budget-line")).toBeTruthy();
    expect(screen.getByText("Locadora X")).toBeTruthy();
    const link = await screen.findByRole("link", { name: "Ver transações" });
    expect(link.getAttribute("href")).toBe("/transacoes?mes=todos&categoria=housing&linha=expenses");
  });

  it("a bar shows its value on hover", async () => {
    setup("/panorama/categoria/housing");
    const bars = await screen.findAllByTestId("cat-bar");
    fireEvent.mouseEnter(bars[1]);
    expect(screen.getByRole("status").textContent).toContain("R$ 300,00");
  });

  it("12 meses: a Sankey category node opens Transações over all months, filtered by that category", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const body = url.includes("/summary/month") ? { month: "2026-10" } : url.includes("/panorama?") ? panorama
        : url.includes("/sankey") ? sankey : url.includes("/transactions?") ? { items: [], next_cursor: null }
        : url.includes("/pnl") ? pnl : url.includes("/channels") ? channels : url.includes("/counterparties") ? counterparties
        : url.endsWith("/accounts") ? [] : taxonomy;
      return new Response(JSON.stringify(body), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <MemoryRouter initialEntries={["/panorama"]}>
            <Routes>
              <Route path="/panorama" element={<Panorama />} />
              <Route path="/transacoes" element={<Transacoes />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /Dividendos/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/transactions?"))).toBe(true));
    const url = String(fetchMock.mock.calls.find(([u]) => String(u).includes("/transactions?"))![0]);
    const q = new URLSearchParams(url.split("?")[1]);
    expect(q.get("category")).toBe("dividends");
    expect(q.has("month")).toBe(false);
  });
});
