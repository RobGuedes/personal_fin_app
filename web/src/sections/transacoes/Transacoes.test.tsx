import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { Shell } from "../../app/Shell";
import type { components } from "../../api/schema";
import { ToastProvider } from "../../components/Toast";
import { Transacoes } from "./Transacoes";

type TxOut = components["schemas"]["TxOut"];
type TxDetail = components["schemas"]["TxDetail"];

function tx(id: string, over: Partial<TxOut> = {}): TxOut {
  return {
    id, date: "2026-10-23", month: "2026-10", description: `Compra ${id}`, counterparty: `Loja ${id}`,
    account: "Cartão Visa", amount: -10, category_id: "groceries", category_label: "Mercado", line: "expenses",
    excluded: false, installment: null, method: "card", source: "pluggy", note: null, in_review: false, ...over,
  };
}

const taxonomy = {
  lines: [
    { id: "income", label: "1. Income" },
    { id: "expenses", label: "4. Expenses" },
    { id: "excluded", label: "(excluded)" },
  ],
  categories: [
    { id: "dividends", line: "income", label: "Dividendos", icon: "💼", color_slot: 2 },
    { id: "groceries", line: "expenses", label: "Mercado", icon: "🛒", color_slot: 1 },
    { id: "restaurants", line: "expenses", label: "Restaurantes", icon: "🍽️", color_slot: 4 },
    { id: "shopping", line: "expenses", label: "Compras", icon: "🛍️", color_slot: 0 },
    { id: "donations", line: "expenses", label: "Doações", icon: "💝", color_slot: 3 },
    { id: "own_transfer", line: "excluded", label: "Transferência entre contas", icon: "🔁", color_slot: null },
  ],
};
const labelOf = (id: string) => taxonomy.categories.find((c) => c.id === id)!.label;
const lineOf = (id: string) => taxonomy.categories.find((c) => c.id === id)!.line;

const ITEMS: TxOut[] = [
  tx("eco", { counterparty: "Empresa X", amount: 8640, category_id: "dividends", category_label: "Dividendos", line: "income", account: "BTG", method: "pix" }),
  tx("magalu", { counterparty: "Magazine Luiza", amount: -149.9, category_id: "shopping", category_label: "Compras", installment: "3/10" }),
  tx("xfer", { counterparty: "Itaú → XP", amount: -5000, category_id: "own_transfer", category_label: "Transferência entre contas", line: "excluded", excluded: true, account: "Itaú", method: "ted_doc" }),
  tx("ong", { date: "2026-10-22", counterparty: "ONG Exemplo", amount: -1120, category_id: "donations", category_label: "Doações" }),
];

const ACCOUNTS = [
  { id: "a1", label: "BTG", type: "BANK", institution: "BTG" },
  { id: "a2", label: "Itaú", type: "BANK", institution: "Itaú" },
  { id: "a3", label: "Conta sem lançamentos", type: "BANK", institution: null },
];

/** The server's today (America/Sao_Paulo); deliberately not the machine's clock. */
const SERVER = { month: "2026-08", day: 14 };

type Handler = (url: string, init?: RequestInit) => Promise<Response> | undefined;
const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

/** Stateful fake API: PATCH changes the stored row, so refetches agree with the edit. */
function setup(handler?: Handler, inShell = false, patchGate?: Promise<void>, entry = "/transacoes") {
  const items = ITEMS.map((x) => ({ ...x }));
  const detail = (x: TxOut): TxDetail => ({ ...x, pluggy_category: "Shopping", transfer_pair: null, suggestion: null });
  const fetchMock = vi.fn((url: string, init?: RequestInit): Promise<Response> => {
    const h = handler?.(url, init);
    if (h) return h;
    const method = init?.method ?? "GET";
    const m = url.match(/\/transactions\/([^?]+)$/);
    if (m) {
      const row = items.find((x) => x.id === decodeURIComponent(m[1]))!;
      if (method === "PATCH" && patchGate) {
        const gate = patchGate;
        patchGate = undefined; // only the first PATCH waits
        return gate.then(() => fetchMock(url, init));
      }
      if (method === "PATCH") {
        const body = JSON.parse(String(init!.body));
        if (body.category_id) {
          row.category_id = body.category_id;
          row.category_label = labelOf(body.category_id);
          row.line = lineOf(body.category_id);
          row.source = "manual";
        }
        if ("note" in body) row.note = body.note;
      }
      return json(detail(row));
    }
    if (url.endsWith("/accounts")) return json(ACCOUNTS);
    if (url.includes("/summary/month")) return json(SERVER);
    if (url.includes("/transactions")) return json({ items, next_cursor: null });
    if (url.endsWith("/rules")) return json({ rule_id: "magazine_luiza_out" });
    return json(taxonomy);
  });
  vi.stubGlobal("fetch", fetchMock);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        {inShell ? (
          <MemoryRouter initialEntries={["/transacoes"]}>
            <Routes>
              <Route element={<Shell />}>
                <Route path="transacoes" element={<Transacoes />} />
              </Route>
            </Routes>
          </MemoryRouter>
        ) : (
          <MemoryRouter initialEntries={[entry]}>
            <Transacoes />
          </MemoryRouter>
        )}
      </ToastProvider>
    </QueryClientProvider>,
  );
  return fetchMock;
}

const listQueries = (f: ReturnType<typeof setup>) =>
  f.mock.calls
    .map(([url]) => url as string)
    .filter((u) => u.startsWith("/api/v1/transactions?"))
    .map((u) => new URLSearchParams(u.split("?")[1]).get("q"));

const calls = (f: ReturnType<typeof setup>, method: string) =>
  f.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method === method)
    .map(([url, init]) => ({ url: url as string, body: JSON.parse(String((init as RequestInit).body)) }));

describe("Transações", () => {
  it("account filter lists every account from /accounts, not only those in the loaded rows", async () => {
    const f = setup();
    await screen.findByText("Empresa X");
    const select = screen.getByLabelText("Conta") as HTMLSelectElement;
    await waitFor(() => expect(within(select).getByRole("option", { name: "Conta sem lançamentos" })).toBeTruthy());
    expect(f.mock.calls.some(([u]) => u === "/api/v1/accounts")).toBe(true);
  });

  it("groups by day and the day total leaves out excluded rows", async () => {
    setup();
    await screen.findByText("Empresa X");
    // 23/10: +9.810,00 − 149,90 = +8.490,10; the −5.000 own transfer is not counted.
    const day23 = screen.getByRole("heading", { name: /SEX 23/ });
    expect(day23.textContent).toContain("+ R$ 8.490,10");
    const day22 = screen.getByRole("heading", { name: /QUI 22/ });
    expect(day22.textContent).toContain("− R$ 1.120,00");
    const xfer = screen.getByRole("button", { name: /Itaú → XP/ });
    expect(xfer.className).toContain("is-excluded");
    expect(within(xfer).getByText(/Transferência entre contas/)).toBeTruthy();
    expect(screen.getByText("3/10")).toBeTruthy();
  });

  it('typing "> 500" sends q="> 500" once, after the debounce', async () => {
    const f = setup();
    await screen.findByText("Empresa X");
    await userEvent.type(screen.getByRole("searchbox", { name: /Buscar/ }), "> 500");
    await waitFor(() => expect(listQueries(f)).toContain("> 500"));
    const sent = listQueries(f).filter((q) => q);
    expect(sent).toEqual(["> 500"]);
  });

  it("/ focuses the search box", async () => {
    setup(undefined, true);
    await screen.findByText("Empresa X");
    await userEvent.keyboard("/");
    expect(document.activeElement).toBe(screen.getByRole("searchbox", { name: /Buscar/ }));
  });

  it("changing the category in the sheet PATCHes and updates the row", async () => {
    const f = setup();
    await userEvent.click(await screen.findByRole("button", { name: /Magazine Luiza/ }));
    const sheet = await screen.findByRole("dialog");
    expect(await within(sheet).findByText("Shopping")).toBeTruthy(); // Pluggy category
    await userEvent.click(within(sheet).getByRole("button", { name: /Restaurantes/ }));
    await waitFor(() =>
      expect(calls(f, "PATCH")).toEqual([{ url: "/api/v1/transactions/magalu", body: { category_id: "restaurants" } }]),
    );
    const row = screen.getByRole("button", { name: /Magazine Luiza/ });
    await waitFor(() => expect(within(row).getByText(/Restaurantes/)).toBeTruthy());
  });

  it("the note saves on blur", async () => {
    const f = setup();
    await userEvent.click(await screen.findByRole("button", { name: /Magazine Luiza/ }));
    const sheet = await screen.findByRole("dialog");
    const note = await within(sheet).findByRole("textbox", { name: /Nota/ });
    await userEvent.type(note, "presente");
    expect(calls(f, "PATCH")).toEqual([]);
    await userEvent.tab();
    await waitFor(() => expect(calls(f, "PATCH")).toEqual([{ url: "/api/v1/transactions/magalu", body: { note: "presente" } }]));
  });

  it("a note still being typed is saved once when the sheet closes", async () => {
    const f = setup();
    await userEvent.click(await screen.findByRole("button", { name: /Magazine Luiza/ }));
    const sheet = await screen.findByRole("dialog");
    await userEvent.type(await within(sheet).findByRole("textbox", { name: /Nota/ }), "presente");
    await userEvent.click(within(sheet).getByRole("button", { name: "Fechar" })); // blur, then close
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(calls(f, "PATCH")).toEqual([{ url: "/api/v1/transactions/magalu", body: { note: "presente" } }]));
  });

  it("Criar regra posts the row and its category; the toast shows the rule id", async () => {
    const f = setup();
    await userEvent.click(await screen.findByRole("button", { name: /Magazine Luiza/ }));
    const sheet = await screen.findByRole("dialog");
    await userEvent.click(await within(sheet).findByRole("button", { name: /Criar regra/ }));
    await waitFor(() =>
      expect(calls(f, "POST")).toEqual([{ url: "/api/v1/rules", body: { transaction_id: "magalu", category_id: "shopping" } }]),
    );
    expect(await screen.findByText(/magazine_luiza_out/)).toBeTruthy();
  });

  it("a 422 from Criar regra shows the API message", async () => {
    setup((url) => (url.endsWith("/rules") ? json({ detail: "Não foi possível criar uma regra." }, 422) : undefined));
    await userEvent.click(await screen.findByRole("button", { name: /Magazine Luiza/ }));
    const sheet = await screen.findByRole("dialog");
    await userEvent.click(await within(sheet).findByRole("button", { name: /Criar regra/ }));
    expect(await screen.findByText("Não foi possível criar uma regra.")).toBeTruthy();
  });

  it("Escape closes the sheet and focus returns to the row", async () => {
    setup();
    const row = await screen.findByRole("button", { name: /Magazine Luiza/ });
    await userEvent.click(row);
    await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /Magazine Luiza/ }));
  });

  it("the period starts on the current month; Todos os meses and Limpar filtros work", async () => {
    const f = setup();
    await screen.findByText("Empresa X");
    const month = SERVER.month;
    const months = () =>
      f.mock.calls.map(([u]) => u as string).filter((u) => u.startsWith("/api/v1/transactions?"))
        .map((u) => new URLSearchParams(u.split("?")[1]).get("month"));
    const period = screen.getByRole("combobox", { name: "Período" }) as HTMLSelectElement;
    expect(period.value).toBe(month);
    expect(months()[0]).toBe(month);
    expect(screen.queryByRole("button", { name: "Limpar filtros" })).toBeNull(); // the default is not a filter
    await userEvent.selectOptions(period, "");
    await waitFor(() => expect(months()).toContain(null));
    await userEvent.click(screen.getByRole("button", { name: "Limpar filtros" }));
    expect(period.value).toBe(month);
    expect(screen.queryByRole("button", { name: "Limpar filtros" })).toBeNull();
  });

  it("text typed while a note save is in flight is kept when the save returns", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    setup(undefined, false, gate);
    await userEvent.click(await screen.findByRole("button", { name: /Magazine Luiza/ }));
    const sheet = await screen.findByRole("dialog");
    const note = (await within(sheet).findByRole("textbox", { name: /Nota/ })) as HTMLTextAreaElement;
    await userEvent.type(note, "presente");
    await userEvent.tab(); // blur: save "presente" (held)
    await userEvent.type(note, " da Ana");
    release();
    await screen.findByText("Nota salva");
    await new Promise((r) => setTimeout(r, 50)); // let the refetches after the save land too
    expect(note.value).toBe("presente da Ana");
  });

  it("Não revisadas filters with unreviewed=true", async () => {
    const f = setup();
    await screen.findByText("Empresa X");
    await userEvent.click(screen.getByRole("button", { name: "Não revisadas" }));
    await waitFor(() =>
      expect(f.mock.calls.some(([u]) => (u as string).includes("unreviewed=true"))).toBe(true),
    );
  });

  it("while more pages remain, the last loaded day's total is not shown as a figure", async () => {
    setup((url) => (url.startsWith("/api/v1/transactions?") && !url.includes("cursor=")
      ? json({ items: ITEMS.map((x) => ({ ...x })), next_cursor: "2026-10-22|ong" }) : undefined));
    await screen.findByText("Empresa X");
    const day23 = screen.getByRole("heading", { name: /SEX 23/ });
    expect(day23.textContent).toContain("+ R$ 8.490,10");
    const day22 = screen.getByRole("heading", { name: /QUI 22/ });
    expect(day22.textContent).not.toContain("R$");
    expect(day22.textContent).toContain("…");
  });

  it("the line filter lists only lines that can match rows, in pt-BR", async () => {
    setup((url) => (url.endsWith("/taxonomy") ? json({
      ...taxonomy,
      lines: [{ id: "income", label: "1. Income" }, { id: "tax_provision", label: "2. Tax provision" },
              { id: "expenses", label: "4. Expenses" }, { id: "net_income", label: "5. Net income" },
              { id: "excluded", label: "(excluded)" }],
    }) : undefined));
    await screen.findByText("Empresa X");
    const select = screen.getByRole("combobox", { name: "Linha do resultado" });
    await waitFor(() => expect(within(select).getAllByRole("option").length).toBeGreaterThan(1));
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Linha do resultado", "Despesas", "Renda", "Fora do resultado"]);
  });

  it("an uncategorized row reads Sem categoria with the ❔ icon", async () => {
    setup((url) => (url.startsWith("/api/v1/transactions?")
      ? json({ items: [tx("pix", { counterparty: "Fulano", category_id: "uncategorized", category_label: null, in_review: true })], next_cursor: null })
      : undefined));
    const row = await screen.findByRole("button", { name: /Fulano/ });
    expect(row.textContent).toContain("Sem categoria");
    expect(row.textContent).toContain("❔");
    expect(row.textContent).not.toMatch(/uncategorized/);
  });

  it("?mes=&linha= deep links preset the period and line filters", async () => {
    const fetchMock = setup(undefined, false, undefined, "/transacoes?mes=2025-03&linha=income");
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/transactions?"))).toBe(true));
    const url = String(fetchMock.mock.calls.find(([u]) => String(u).includes("/transactions?"))![0]);
    const q = new URLSearchParams(url.split("?")[1]);
    expect(q.get("month")).toBe("2025-03");
    expect(q.get("line")).toBe("income");
    expect((screen.getByRole("combobox", { name: "Período" }) as HTMLSelectElement).value).toBe("2025-03");
  });

  it("?mes=todos (multi-month drill-downs) opens on all months", async () => {
    const fetchMock = setup(undefined, false, undefined, "/transacoes?mes=todos&categoria=housing");
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/transactions?"))).toBe(true));
    const url = String(fetchMock.mock.calls.find(([u]) => String(u).includes("/transactions?"))![0]);
    const q = new URLSearchParams(url.split("?")[1]);
    expect(q.has("month")).toBe(false);
    expect(q.get("category")).toBe("housing");
    expect((screen.getByRole("combobox", { name: "Período" }) as HTMLSelectElement).value).toBe("");
  });

  it("the current month and HOJE come from the server, not the browser clock", async () => {
    const fetchMock = setup((url) =>
      url.includes("/transactions?") ? json({ items: [tx("hoje", { date: "2026-08-14", month: "2026-08" })], next_cursor: null }) : undefined);
    expect(await screen.findByText("Loja hoje")).toBeTruthy();
    expect(screen.getByRole("region", { name: /^HOJE/ })).toBeTruthy();
    const url = String(fetchMock.mock.calls.find(([u]) => String(u).includes("/transactions?"))![0]);
    expect(new URLSearchParams(url.split("?")[1]).get("month")).toBe("2026-08");
  });

  it("plain /transacoes still opens on the current month", async () => {
    const fetchMock = setup();
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/transactions?"))).toBe(true));
    const url = String(fetchMock.mock.calls.find(([u]) => String(u).includes("/transactions?"))![0]);
    expect(new URLSearchParams(url.split("?")[1]).get("month")).toBe(SERVER.month);
  });

  it("ignores a malformed mes", async () => {
    const fetchMock = setup(undefined, false, undefined, "/transacoes?mes=2025-13");
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/transactions?"))).toBe(true));
    const url = String(fetchMock.mock.calls.find(([u]) => String(u).includes("/transactions?"))![0]);
    expect(new URLSearchParams(url.split("?")[1]).get("month")).toBe(SERVER.month);
  });
});
