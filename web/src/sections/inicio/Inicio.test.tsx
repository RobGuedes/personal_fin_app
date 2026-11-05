import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import type { components } from "../../api/schema";
import { Inicio } from "./Inicio";

type MonthSummary = components["schemas"]["MonthSummary"];
type Cat = components["schemas"]["CategoryStatusOut"];

function cat(id: string, spent: number, ref: number | null, extra: Partial<Cat> = {}): Cat {
  return { category_id: id, spent, reference_to_date: ref, reference_month: ref === null ? null : ref * 1.3,
           reference_kind: ref === null ? "none" : "usual", unusual: false, pct_over: null, note: null, ...extra };
}

function summary(over: Partial<MonthSummary> = {}): MonthSummary {
  return {
    month: "2026-10", day: 24, days_in_month: 31, is_current: true,
    totals: { income: 54900, tax_provision: -1550, commissions: -2000, expenses: -30750, net_income: 20600 },
    renda_split: { renda: 54900, despesas: 30750, outros: 3550, sobrou: 20600, scale: 54900, deficit: false },
    spending: { spent: 24300, reference_to_date: 29800, reference_month: 36000 },
    categories: [
      cat("housing", 6150, 3575, { unusual: true, pct_over: 0.72, note: "ar-condicionado" }),
      cat("restaurants", 2140, 1550, { unusual: true, pct_over: 0.38 }),
      cat("education", 1930, 1930), cat("groceries", 610, 600), cat("transport", 420, 500),
      cat("health", 300, 280), cat("leisure", 120, null),
    ],
    income_sources: [
      { key: "dividends", label: "Dividendos e rendimentos", amount: 35685 },
      { key: "services_nf", label: "Serviços (NF)", amount: 13725 },
      { key: "manual:income", label: "Lançamentos manuais", amount: 5490 },
    ],
    review_count: 7,
    ...over,
  };
}

const taxonomy = {
  lines: [],
  categories: [
    { id: "housing", line: "expenses", label: "Moradia", icon: "🏠", color_slot: 1 },
    { id: "restaurants", line: "expenses", label: "Restaurantes", icon: "🍽️", color_slot: 4 },
    { id: "education", line: "expenses", label: "Educação", icon: "🎓", color_slot: 0 },
    { id: "dividends", line: "income", label: "Dividendos e rendimentos", icon: "📈", color_slot: 0 },
    { id: "services_nf", line: "income", label: "Serviços (NF)", icon: "🧾", color_slot: 1 },
  ],
};
const trend = ["05", "06", "07", "08", "09", "10"].map((m, i) => ({ month: `2026-${m}`, income: 40000 + i * 1000, spending: 30000 }));

const sankeyBody = {
  nodes: [
    { id: "src:dividends", label: "Dividendos", side: "source", key: "dividends", value: 600, filter: { category: "dividends" } },
    { id: "mid", label: "Renda", side: "middle", key: "renda", value: 600, filter: null, income: 600 },
    { id: "dst:restaurants", label: "Restaurantes", side: "target", key: "restaurants", value: 400, filter: { category: "restaurants" } },
    { id: "dst:sobrou", label: "Sobrou", side: "target", key: "sobrou", value: 200, filter: null },
  ],
  links: [
    { source: "src:dividends", target: "mid", value: 600 },
    { source: "mid", target: "dst:restaurants", value: 400 },
    { source: "mid", target: "dst:sobrou", value: 200 },
  ],
};

function stubMedia(matches: boolean) {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches, media: q, addEventListener: () => {}, removeEventListener: () => {},
  }));
}

type Override = (url: string) => Promise<Response> | undefined;

function setup(s: MonthSummary, override?: Override) {
  const fetchMock = vi.fn(async (url: string) => {
    const o = override?.(url);
    if (o) return o;
    const body = url.includes("/sankey") ? sankeyBody : url.includes("/summary/month") ? s : url.includes("/trend") ? trend : taxonomy;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Inicio />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetchMock;
}

/** The category row named `name` (the name also appears in the doughnut legend). */
async function rowOf(name: string): Promise<HTMLElement> {
  const rows = await screen.findAllByTestId("category-row");
  const row = rows.find((r) => r.querySelector(".cat-name")?.textContent?.includes(name));
  if (!row) throw new Error(`no row ${name}`);
  return row;
}

const catsCard = async () => (await rowOf("")).closest(".cats-card") as HTMLElement;

describe("Inicio", () => {
  it("shows the month header, Sobrou and renda from the summary", async () => {
    setup(summary());
    expect(await screen.findByText("R$ 20.600")).toBeTruthy();
    expect(screen.getByText("Outubro · dia 24 de 31")).toBeTruthy();
    expect(screen.getByText("Sobrou este mês")).toBeTruthy();
    expect(screen.getByText("de R$ 54.900 de renda")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Para onde foi sua renda/ }).getAttribute("href")).toBe("/panorama");
    expect(screen.getByRole("link", { name: /7 para revisar/ }).getAttribute("href")).toBe("/revisar");
    expect(screen.getByText("R$ 24.300 de R$ 29.800 até o dia 24")).toBeTruthy();
  });

  it("shows the unusual note text with the % over", async () => {
    setup(summary());
    const row = await rowOf("Moradia");
    expect(within(row).getByText("+72%")).toBeTruthy();
    expect(within(row).getByText(/ar-condicionado/)).toBeTruthy();
    expect(within(row).getByText("R$ 6.150")).toBeTruthy();
  });

  it("hides the review card when review_count = 0", async () => {
    setup(summary({ review_count: 0 }));
    await screen.findByText("R$ 20.600");
    expect(screen.queryByText(/para revisar/)).toBeNull();
  });

  it("deficit shows Faltou from renda_split.sobrou in the warning color", async () => {
    setup(summary({
      // net_income deliberately differs: the hero must follow the split (same source as the bar)
      totals: { income: 10000, tax_provision: 0, commissions: -1000, expenses: -10500, net_income: -1499 },
      renda_split: { renda: 10000, despesas: 10500, outros: 1000, sobrou: -1500, scale: 11500, deficit: true },
    }));
    expect(await screen.findByText("Faltou este mês")).toBeTruthy();
    const value = screen.getByText("R$ 1.500");
    expect(value.classList.contains("is-short")).toBe(true);
    expect(screen.queryByText("R$ 1.499")).toBeNull();
  });

  it("review card uses the mockup copy", async () => {
    setup(summary({ review_count: 40 }));
    expect(await screen.findByText("menos de 1 minuto")).toBeTruthy();
  });

  it("no empty note when unusual has neither pct_over nor note", async () => {
    setup(summary({ categories: [cat("housing", 6150, 3575, { unusual: true })] }));
    const row = await rowOf("Moradia");
    expect(row.querySelector(".cat-note")).toBeNull();
  });

  it("category bar has one accessible name and no duplicate title", async () => {
    setup(summary());
    const row = await rowOf("Moradia");
    expect(row.hasAttribute("title")).toBe(false);
    expect(row.querySelectorAll("[title]")).toHaveLength(0);
    expect(within(row).getAllByRole("img")).toHaveLength(1);
  });

  it("top 5 categories, then expands to all in place", async () => {
    setup(summary());
    await rowOf("Moradia");
    expect(screen.getAllByTestId("category-row")).toHaveLength(5);
    await userEvent.setup().click(screen.getByRole("button", { name: /Ver todas as 7 categorias/ }));
    expect(screen.getAllByTestId("category-row")).toHaveLength(7);
  });

  it("past month: full-month figures, no next beyond the latest month", async () => {
    const fetchMock = setup(summary());
    await screen.findByText("R$ 20.600");
    expect((screen.getByRole("button", { name: "Próximo mês" }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.setup().click(screen.getByRole("button", { name: "Mês anterior" }));
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes("month=2026-09"))).toBe(true);
  });

  it("previous-month button is disabled at the first month with data", async () => {
    const ov: Override = (u) => (u.includes("/taxonomy") ? Promise.resolve(new Response(JSON.stringify({ ...taxonomy, first_month: "2026-09" }))) : undefined);
    setup(summary(), ov);
    await screen.findByText("R$ 20.600");
    const prev = () => screen.getByRole("button", { name: "Mês anterior" }) as HTMLButtonElement;
    await vi.waitFor(() => expect(prev().disabled).toBe(false));
    await userEvent.setup().click(prev());
    await vi.waitFor(() => expect(screen.getByText("Setembro 2026")).toBeTruthy());
    expect(prev().disabled).toBe(true);
  });

  it("'Ver todas' count equals the categories listed (zero-spend ones are neither counted nor shown)", async () => {
    setup(summary({ categories: [...summary().categories, cat("pets", 0, 80)] }));
    await rowOf("Moradia");
    await userEvent.setup().click(screen.getByRole("button", { name: /Ver todas as 7 categorias/ }));
    expect(screen.getAllByTestId("category-row")).toHaveLength(7);
  });

  it("creates the media query list once, not on every render", async () => {
    const calls: string[] = [];
    vi.stubGlobal("matchMedia", (q: string) => {
      calls.push(q);
      return { matches: false, media: q, addEventListener: () => {}, removeEventListener: () => {} };
    });
    setup(summary());
    await rowOf("Moradia");
    await userEvent.setup().click(screen.getByRole("button", { name: /Ver todas/ }));
    await userEvent.setup().click(screen.getByRole("button", { name: /Mostrar menos/ }));
    expect(calls.length).toBeLessThanOrEqual(1);
  });

  it("past month: header, hero and note show full-month figures", async () => {
    const sept = summary({ month: "2026-09", day: 30, days_in_month: 30, is_current: false });
    setup(summary(), (u) => (u.includes("month=2026-09") ? Promise.resolve(new Response(JSON.stringify(sept))) : undefined));
    await screen.findByText("R$ 20.600");
    await userEvent.setup().click(screen.getByRole("button", { name: "Mês anterior" }));
    expect(await screen.findByText("Setembro 2026")).toBeTruthy();
    expect(screen.getByText("Sobrou em setembro")).toBeTruthy();
    expect(screen.getByText("R$ 24.300 de R$ 29.800 no mês")).toBeTruthy();
    expect(screen.queryByText(/dia \d+ de/)).toBeNull();
    expect((screen.getByRole("button", { name: "Próximo mês" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("keeps the header, picker and previous figures while the next month loads", async () => {
    setup(summary(), (u) => (u.includes("month=2026-09") ? new Promise<Response>(() => {}) : undefined));
    await screen.findByText("R$ 20.600");
    await userEvent.setup().click(screen.getByRole("button", { name: "Mês anterior" }));
    expect(screen.getByText("Setembro 2026")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Mês anterior" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Próximo mês" })).toBeTruthy();
    expect(screen.getByText("R$ 20.600")).toBeTruthy();
  });

  it("error on a past month keeps the picker and offers going back to the current month", async () => {
    setup(summary(), (u) =>
      u.includes("month=2026-09") ? Promise.resolve(new Response(JSON.stringify({ error: "falhou" }), { status: 500 })) : undefined);
    await screen.findByText("R$ 20.600");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Mês anterior" }));
    expect((await screen.findByRole("alert")).textContent).toContain("falhou");
    expect(screen.getByText("Setembro 2026")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Próximo mês" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Voltar ao mês atual" }));
    expect(await screen.findByText("Outubro · dia 24 de 31")).toBeTruthy();
    expect(screen.getByText("R$ 20.600")).toBeTruthy();
  });

  it("an uncategorized row reads Sem categoria with the ❔ icon, never the raw id", async () => {
    setup(summary({ categories: [cat("uncategorized", 900, null)] }));
    const row = await rowOf("Sem categoria");
    expect(row.textContent).toContain("❔");
    expect(row.textContent).not.toMatch(/uncategorized/);
    expect(within(row).getByRole("img").getAttribute("aria-label")).toMatch(/^Sem categoria:/);
  });

  describe("De onde veio sua renda", () => {
    const card = async () => (await screen.findByRole("link", { name: /De onde veio sua renda/ }));

    it("sits above Para onde foi and links to the month's income transactions", async () => {
      setup(summary());
      const from = await card();
      const to = screen.getByRole("link", { name: /Para onde foi sua renda/ });
      expect(from.getAttribute("href")).toBe("/transacoes?mes=2026-10&linha=income");
      expect(from.compareDocumentPosition(to) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it("legend: name, % of income and compact value, largest first", async () => {
      setup(summary());
      const items = within(await card()).getAllByRole("listitem").map((li) => li.textContent);
      expect(items).toEqual([
        "Dividendos e rendimentos 65% · R$ 35,7 mil",
        "Serviços (NF) 25% · R$ 13,7 mil",
        "Lançamentos manuais 10% · R$ 5,5 mil",
      ]);
      const bar = within(await card()).getByRole("img");
      expect(bar.getAttribute("aria-label")).toMatch(/^De onde veio sua renda: Dividendos e rendimentos 65% \(R\$ 35\.685,00\)/);
    });

    it("segments use the category color slot, gray without one", async () => {
      setup(summary());
      const segs = within(await card()).getAllByTestId("income-segment");
      expect(segs.map((b) => b.style.background)).toEqual(["var(--cat-0)", "var(--cat-1)", "var(--cat-other)"]);
    });

    it("more than 5 sources fold the rest into a gray Outras fontes", async () => {
      const sources = [9000, 8000, 7000, 6000, 5000, 4000, 3000].map((amount, i) => ({ key: `k${i}`, label: `Fonte ${i}`, amount }));
      setup(summary({ income_sources: sources }));
      const c = await card();
      expect(within(c).getAllByTestId("income-segment")).toHaveLength(6);
      const items = within(c).getAllByRole("listitem");
      expect(items[5].textContent).toBe("Outras fontes 17% · R$ 7 mil");
      expect(within(c).getAllByTestId("income-segment")[5].style.background).toBe("var(--cat-other)");
    });

    it("hidden when the month has no income", async () => {
      setup(summary({ totals: { ...summary().totals, income: 0 }, income_sources: [] }));
      await screen.findByText("Para onde foi sua renda");
      expect(screen.queryByText("De onde veio sua renda")).toBeNull();
    });
  });

  describe("spending doughnut", () => {
    it("top 5 categories + Outras, total in the hole, legend % of spent", async () => {
      setup(summary());
      const card = await catsCard();
      expect(within(card).getAllByTestId("donut-slice")).toHaveLength(6);
      // categories sum 11670 (the hole shows the sum of categories[].spent)
      expect(within(card).getByTestId("donut-total").textContent).toBe("R$ 11,7 mil");
      expect(within(card).getByText("gastos")).toBeTruthy();
      const legend = [...card.querySelectorAll(".donut-legend li")].map((li) => li.textContent);
      expect(legend).toEqual(["Moradia 53%", "Restaurantes 18%", "Educação 17%", "groceries 5%", "transport 4%", "Outras 4%"]);
      // rows below are unchanged
      expect(screen.getAllByTestId("category-row")).toHaveLength(5);
    });

    it("slices take the rows' colors; Outras is gray; % on slices >= 8% only", async () => {
      setup(summary());
      const card = await catsCard();
      const slices = within(card).getAllByTestId("donut-slice");
      expect(slices.map((p) => p.getAttribute("fill"))).toEqual(
        ["var(--cat-1)", "var(--cat-4)", "var(--cat-0)", "var(--cat-other)", "var(--cat-other)", "var(--cat-other)"]);
      expect([...card.querySelectorAll(".donut-pct")].map((el) => el.textContent)).toEqual(["53%", "18%", "17%"]);
    });

    it("no Outras with 5 or fewer categories", async () => {
      setup(summary({ categories: [cat("housing", 600, null), cat("restaurants", 400, null)] }));
      const card = await catsCard();
      expect(within(card).getAllByTestId("donut-slice")).toHaveLength(2);
      expect(card.querySelector(".donut-legend")!.textContent).not.toContain("Outras");
      expect(within(card).getByTestId("donut-total").textContent).toBe("R$ 1 mil");
    });

    it("hovering or focusing a slice shows name, R$ value and %", async () => {
      setup(summary());
      const card = await catsCard();
      const user = userEvent.setup();
      await user.hover(within(card).getAllByTestId("donut-slice")[0]);
      const tip = within(card).getByTestId("donut-tip");
      expect(tip.getAttribute("role")).toBeNull(); // the slice's aria-label is the announcement
      expect(tip.getAttribute("aria-hidden")).toBe("true");
      expect(tip.textContent).toContain("Moradia");
      expect(tip.textContent).toContain("R$ 6.150,00 · 53%");
      within(card).getAllByTestId("donut-slice")[1].focus();
      expect(await within(card).findByText(/R\$ 2\.140,00 · 18%/)).toBeTruthy();
    });
  });

  describe("review fixes", () => {
    it("income: exactly 6 sources are shown as-is, no Outras fontes", async () => {
      const sources = [9000, 8000, 7000, 6000, 5000, 4000].map((amount, i) => ({ key: `k${i}`, label: `Fonte ${i}`, amount }));
      setup(summary({ income_sources: sources }));
      const c = await screen.findByRole("link", { name: /De onde veio sua renda/ });
      expect(within(c).getAllByTestId("income-segment")).toHaveLength(6);
      expect(c.textContent).not.toContain("Outras fontes");
    });

    it("income: a note when manual entries are included (Transações cannot list them)", async () => {
      setup(summary());
      const c = await screen.findByRole("link", { name: /De onde veio sua renda/ });
      expect(within(c).getByText("Inclui lançamentos manuais, que não aparecem em Transações")).toBeTruthy();
    });

    it("income: no note without manual entries", async () => {
      setup(summary({ income_sources: [{ key: "dividends", label: "Dividendos e rendimentos", amount: 54900 }] }));
      const c = await screen.findByRole("link", { name: /De onde veio sua renda/ });
      expect(c.textContent).not.toContain("lançamentos manuais, que");
    });

    it("doughnut: exactly 6 categories are shown as-is, no Outras", async () => {
      setup(summary({ categories: summary().categories.slice(0, 6) }));
      const card = await catsCard();
      expect(within(card).getAllByTestId("donut-slice")).toHaveLength(6);
      expect(card.querySelector(".donut-legend")!.textContent).not.toContain("Outras");
    });

    it("doughnut: side slices anchor the tooltip inward", async () => {
      setup(summary());
      const card = await catsCard();
      const user = userEvent.setup();
      const classes: string[] = [];
      for (const slice of within(card).getAllByTestId("donut-slice")) {
        await user.hover(slice);
        classes.push(within(card).getByTestId("donut-tip").className);
      }
      expect(classes.some((c) => c.includes("tip-start"))).toBe(true);
      expect(classes.some((c) => c.includes("tip-end"))).toBe(true);
    });
  });
});

describe("Inicio Sankey", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("desktop (>= 1024px) shows the month's Sankey and requests it for that month", async () => {
    stubMedia(true);
    const fetchMock = setup(summary());
    expect(await screen.findByLabelText("Restaurantes: R$ 400,00 (67%)")).toBeTruthy();
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("/sankey?period=month%3A2026-10"))).toBe(true);
  });

  it("phone shows no Sankey and does not fetch it", async () => {
    stubMedia(false);
    const fetchMock = setup(summary());
    await screen.findAllByTestId("category-row");
    expect(screen.queryByLabelText(/Restaurantes: R\$ 400/)).toBeNull();
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("/sankey"))).toBe(false);
  });
});
