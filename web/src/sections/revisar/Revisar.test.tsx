import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import type { components } from "../../api/schema";
import { ToastProvider } from "../../components/Toast";
import { Revisar } from "./Revisar";

type ReviewItem = components["schemas"]["ReviewItem"];

function item(id: string, over: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id, date: "2026-07-14", month: "2026-07", description: "Pix enviado", counterparty: `Pessoa ${id}`,
    account: "Itaú", amount: -1600, category_id: "uncategorized", category_label: null, line: "expenses",
    excluded: false, installment: null, method: "pix", source: null, note: null, in_review: true,
    suggestion: null, top_categories: ["groceries", "restaurants"], ...over,
  };
}

const taxonomy = {
  lines: [
    { id: "income", label: "1. Income" },
    { id: "expenses", label: "5. Expenses" },
    { id: "excluded", label: "(excluded)" },
  ],
  categories: [
    { id: "salary", line: "income", label: "Salário", icon: "💼", color_slot: 2 },
    { id: "housing", line: "expenses", label: "Moradia", icon: "🏠", color_slot: 1 },
    { id: "groceries", line: "expenses", label: "Mercado", icon: "🛒", color_slot: 3 },
    { id: "restaurants", line: "expenses", label: "Restaurantes", icon: "🍽️", color_slot: 4 },
    { id: "education", line: "expenses", label: "Educação", icon: "🎓", color_slot: 0 },
    { id: "own_transfer", line: "excluded", label: "Transferência entre contas", icon: "🔁", color_slot: null },
  ],
};

const A = item("a", {
  counterparty: "Pessoa B Exemplo",
  suggestion: { category_id: "housing", reason: "past_choice", detail: "Pix de 01/07 para o mesmo nome foi Moradia" },
});
const B = item("b", { description: "Compra débito Padaria", counterparty: "Padaria Pão Bom" });
const PREV = { category_id: "other_expense", source: "pluggy", rule_id: null, confidence: 0.5 };

type Handler = (url: string, init?: RequestInit) => Promise<Response> | undefined;
const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

/** Stateful fake API: confirm removes the item from the inbox, undo puts it back in its place. */
function setup(items: ReviewItem[], handler?: Handler) {
  const order = items.map((x) => x.id);
  let inbox = [...items];
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const h = handler?.(url, init);
    if (h) return h;
    const id = decodeURIComponent(url.split("/review/")[1]?.split("/")[0] ?? "");
    if (url.endsWith("/confirm")) {
      inbox = inbox.filter((x) => x.id !== id);
      return json({ previous: PREV, rule_id: null });
    }
    if (url.endsWith("/undo")) {
      const back = items.find((x) => x.id === id);
      if (back && !inbox.some((x) => x.id === id)) {
        inbox = [...inbox, back].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
      }
      return json({ ok: true });
    }
    if (url.includes("/review")) return json(inbox);
    return json(taxonomy);
  });
  vi.stubGlobal("fetch", fetchMock);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <Revisar />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return fetchMock;
}

const gets = (f: ReturnType<typeof setup>) =>
  f.mock.calls.filter(([url, init]) => (url as string).endsWith("/review") && (init as RequestInit | undefined)?.method === "GET").length;

const posts = (f: ReturnType<typeof setup>) =>
  f.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method === "POST")
    .map(([url, init]) => ({ url: url as string, body: JSON.parse(String((init as RequestInit).body)) }));

describe("Revisar", () => {
  it("shows the card with progress, suggestion and chips", async () => {
    setup([A, B]);
    expect(await screen.findByText("Pessoa B Exemplo")).toBeTruthy();
    expect(screen.getByText("1 de 2")).toBeTruthy();
    expect(screen.getByText("Pix de 01/07 para o mesmo nome foi Moradia")).toBeTruthy();
    const chips = screen.getAllByRole("button", { pressed: true });
    expect(chips.map((c) => c.textContent)).toEqual(["🏠 Moradia"]);
    expect(screen.getByRole("button", { name: /Mercado/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Transferência entre contas/ })).toBeTruthy();
    expect(screen.getByRole("switch", { name: /Sempre usar para/ })).toBeTruthy();
  });

  it("Enter confirms the pre-selected suggestion and moves to the next card", async () => {
    const f = setup([A, B]);
    await screen.findByText("Pessoa B Exemplo");
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByText("Padaria Pão Bom")).toBeTruthy();
    expect(screen.getByText("2 de 2")).toBeTruthy();
    expect(posts(f)).toEqual([{ url: "/api/v1/review/a/confirm", body: { category_id: "housing", create_rule: false } }]);
    expect(await screen.findByText("Classificado como Moradia")).toBeTruthy();
  });

  it("2 then Enter confirms the second chip", async () => {
    const f = setup([A, B]);
    await screen.findByText("Pessoa B Exemplo");
    await userEvent.keyboard("2");
    expect(screen.getByRole("button", { name: /Mercado/ }).getAttribute("aria-pressed")).toBe("true");
    await userEvent.keyboard("{Enter}");
    await screen.findByText("Padaria Pão Bom");
    expect(posts(f)[0].body.category_id).toBe("groceries");
  });

  it("S skips without a request", async () => {
    const f = setup([A, B]);
    await screen.findByText("Pessoa B Exemplo");
    await userEvent.keyboard("s");
    expect(await screen.findByText("Padaria Pão Bom")).toBeTruthy();
    expect(screen.getByText("2 de 2")).toBeTruthy();
    expect(posts(f)).toEqual([]);
  });

  it("U calls undo with the stored previous and brings the card back", async () => {
    const f = setup([A, B]);
    await screen.findByText("Pessoa B Exemplo");
    await userEvent.keyboard("{Enter}");
    await screen.findByText("Padaria Pão Bom");
    await userEvent.keyboard("u");
    expect(await screen.findByText("Pessoa B Exemplo")).toBeTruthy();
    expect(posts(f)[1]).toEqual({ url: "/api/v1/review/a/undo", body: { previous: PREV } });
  });

  it("the toast's Desfazer undoes that confirmation", async () => {
    const f = setup([A, B]);
    await screen.findByText("Pessoa B Exemplo");
    await userEvent.click(screen.getByRole("button", { name: /Confirmar/ }));
    const toast = (await screen.findByText("Classificado como Moradia")).closest(".toast") as HTMLElement;
    await userEvent.click(within(toast).getByRole("button", { name: "Desfazer" }));
    expect(await screen.findByText("Pessoa B Exemplo")).toBeTruthy();
    expect(posts(f)[1].url).toBe("/api/v1/review/a/undo");
  });

  it("disables Confirmar while the request is in flight (no double submit)", async () => {
    let release: (r: Response) => void = () => {};
    const f = setup([A, B], (url) =>
      url.endsWith("/confirm") ? new Promise<Response>((r) => (release = r)) : undefined,
    );
    await screen.findByText("Pessoa B Exemplo");
    const button = screen.getByRole("button", { name: /Confirmar/ });
    await userEvent.click(button);
    expect((button as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(button);
    await userEvent.keyboard("{Enter}");
    expect(posts(f)).toHaveLength(1);
    await act(async () => release(new Response(JSON.stringify({ previous: null, rule_id: null }), { status: 200 })));
    expect(await screen.findByText("Padaria Pão Bom")).toBeTruthy();
  });

  it("sends the note and create_rule, and mentions the new rule", async () => {
    const f = setup([A, B], (url) => (url.endsWith("/confirm") ? json({ previous: null, rule_id: "r12" }) : undefined));
    await screen.findByText("Pessoa B Exemplo");
    await userEvent.click(screen.getByRole("switch", { name: /Sempre usar para/ }));
    await userEvent.type(screen.getByPlaceholderText(/Nota/), "eletricista{Enter}");
    await screen.findByText("Padaria Pão Bom");
    expect(posts(f)[0].body).toEqual({ category_id: "housing", create_rule: true, note: "eletricista" });
    expect(await screen.findByText("Classificado como Moradia · regra criada")).toBeTruthy();
  });

  it("digits typed in the note do not pick chips", async () => {
    setup([A, B]);
    await screen.findByText("Pessoa B Exemplo");
    await userEvent.type(screen.getByPlaceholderText(/Nota/), "2");
    expect(screen.getByRole("button", { name: /Moradia/ }).getAttribute("aria-pressed")).toBe("true");
  });

  it("shows the API error when the rule cannot be created and stays on the card", async () => {
    setup([A, B], (url) =>
      url.endsWith("/confirm") ? json({ error: "Não foi possível criar uma regra" }, 422) : undefined,
    );
    await screen.findByText("Pessoa B Exemplo");
    await userEvent.click(screen.getByRole("switch", { name: /Sempre usar para/ }));
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByText("Não foi possível criar uma regra")).toBeTruthy();
    expect(screen.getByText("Pessoa B Exemplo")).toBeTruthy();
  });

  it("swipe right past 80px confirms", async () => {
    const f = setup([A, B]);
    const name = await screen.findByText("Pessoa B Exemplo");
    const card = name.closest("form") as HTMLElement;
    fireEvent.pointerDown(card, { pointerType: "touch", clientX: 10, clientY: 100, pointerId: 1 });
    fireEvent.pointerMove(card, { pointerType: "touch", clientX: 60, clientY: 102, pointerId: 1 });
    fireEvent.pointerUp(card, { pointerType: "touch", clientX: 60, clientY: 102, pointerId: 1 });
    expect(posts(f)).toEqual([]);
    fireEvent.pointerDown(card, { pointerType: "touch", clientX: 10, clientY: 100, pointerId: 2 });
    fireEvent.pointerMove(card, { pointerType: "touch", clientX: 120, clientY: 104, pointerId: 2 });
    fireEvent.pointerUp(card, { pointerType: "touch", clientX: 120, clientY: 104, pointerId: 2 });
    expect(await screen.findByText("Padaria Pão Bom")).toBeTruthy();
    expect(posts(f)).toHaveLength(1);
  });

  it("⋯ Outra opens a searchable list (accent-insensitive) grouped by line", async () => {
    const f = setup([A, B]);
    await screen.findByText("Pessoa B Exemplo");
    await userEvent.click(screen.getByRole("button", { name: /Outra/ }));
    expect(screen.getByRole("group", { name: "Despesas" })).toBeTruthy();
    await userEvent.type(screen.getByRole("searchbox"), "educacao");
    await userEvent.click(screen.getByRole("option", { name: /Educação/ }));
    expect(screen.getByRole("button", { name: /Educação/ }).getAttribute("aria-pressed")).toBe("true");
    await userEvent.keyboard("{Enter}");
    await screen.findByText("Padaria Pão Bom");
    expect(posts(f)[0].body.category_id).toBe("education");
  });

  it("Outra lists every line, the outflow's lines first", async () => {
    setup([A, B]);
    await screen.findByText("Pessoa B Exemplo");
    await userEvent.click(screen.getByRole("button", { name: /Outra/ }));
    const list = screen.getByRole("listbox");
    const groups = within(list).getAllByRole("group").map((g) => g.getAttribute("aria-label"));
    expect(groups).toEqual(["Despesas", "Renda", "Fora do resultado"]);
    expect(within(list).getAllByRole("option", { name: /Transferência entre contas/ })).toHaveLength(1);
  });

  it("an outflow can pick an income category", async () => {
    const f = setup([A, B]);
    await screen.findByText("Pessoa B Exemplo");
    await userEvent.click(screen.getByRole("button", { name: /Outra/ }));
    await userEvent.click(screen.getByRole("option", { name: /Salário/ }));
    await userEvent.keyboard("{Enter}");
    await screen.findByText("Padaria Pão Bom");
    expect(posts(f)[0].body.category_id).toBe("salary");
  });

  it("an inflow (refund, share paid back) lists Renda first and can pick an expense category", async () => {
    const refund = item("r", { amount: 45, counterparty: "Amigo da pizza", top_categories: ["salary"] });
    const f = setup([refund, B]);
    await screen.findByText("Amigo da pizza");
    expect(screen.getByRole("button", { name: /Salário/ })).toBeTruthy(); // inflow chips from top_categories
    await userEvent.click(screen.getByRole("button", { name: /Outra/ }));
    const groups = within(screen.getByRole("listbox")).getAllByRole("group").map((g) => g.getAttribute("aria-label"));
    expect(groups).toEqual(["Renda", "Despesas", "Fora do resultado"]);
    await userEvent.type(screen.getByRole("searchbox"), "restaur");
    await userEvent.click(screen.getByRole("option", { name: /Restaurantes/ }));
    await userEvent.keyboard("{Enter}");
    await screen.findByText("Padaria Pão Bom");
    expect(posts(f)[0].body.category_id).toBe("restaurants");
  });

  it("shows the empty state with a link to Início", async () => {
    setup([]);
    expect(await screen.findByText("Nada para revisar 🎉")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Início/ }).getAttribute("href")).toBe("/");
  });

  it("after the last card shows the empty state too", async () => {
    setup([A]);
    await screen.findByText("Pessoa B Exemplo");
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByText("Nada para revisar 🎉")).toBeTruthy();
  });

  describe("against a refetching inbox", () => {
    it("the confirmed item leaves the server list; the next card and progress stay right", async () => {
      const f = setup([A, B]);
      await screen.findByText("Pessoa B Exemplo");
      await userEvent.keyboard("{Enter}");
      expect(await screen.findByText("Padaria Pão Bom")).toBeTruthy();
      await waitFor(() => expect(gets(f)).toBeGreaterThanOrEqual(2)); // refetched without A
      expect(screen.getByText("2 de 2")).toBeTruthy();
    });

    it("after undo the undone card shows at once (before the refetch) and Enter confirms that card", async () => {
      let hold: ((r: Response) => void) | null = null;
      let undone = false;
      const f = setup([A, B], (url, init) => {
        if (url.endsWith("/undo")) undone = true;
        if (undone && url.endsWith("/review") && init?.method === "GET") return new Promise<Response>((r) => (hold = r));
        return undefined;
      });
      await screen.findByText("Pessoa B Exemplo");
      await userEvent.keyboard("{Enter}");
      await screen.findByText("Padaria Pão Bom");
      await waitFor(() => expect(gets(f)).toBeGreaterThanOrEqual(2));
      await userEvent.keyboard("u");
      // the post-undo refetch is still pending: A comes from the local copy
      expect(await screen.findByText("Pessoa B Exemplo")).toBeTruthy();
      expect(hold).not.toBeNull();
      expect(screen.getByText("1 de 2")).toBeTruthy();
      await userEvent.keyboard("{Enter}");
      await waitFor(() => expect(posts(f).map((p) => p.url)).toEqual([
        "/api/v1/review/a/confirm", "/api/v1/review/a/undo", "/api/v1/review/a/confirm",
      ]));
      expect(await screen.findByText("Padaria Pão Bom")).toBeTruthy();
    });

    it("U consumes the entry: the toast's Desfazer is gone and no second undo is sent", async () => {
      const f = setup([A, B]);
      await screen.findByText("Pessoa B Exemplo");
      await userEvent.keyboard("{Enter}");
      await screen.findByText("Classificado como Moradia");
      await userEvent.keyboard("u");
      await screen.findByText("Classificação desfeita");
      expect(screen.queryByText("Classificado como Moradia")).toBeNull();
      expect(screen.queryByRole("button", { name: "Desfazer" })).toBeNull();
      await userEvent.keyboard("u"); // nothing left to undo
      expect(posts(f).filter((p) => p.url.endsWith("/undo"))).toHaveLength(1);
    });

    it("Pular and S do nothing while a confirm is in flight", async () => {
      let release: (r: Response) => void = () => {};
      setup([A, B, item("c", { counterparty: "Terceiro" })], (url) =>
        url.endsWith("/confirm") ? new Promise<Response>((r) => (release = r)) : undefined,
      );
      await screen.findByText("Pessoa B Exemplo");
      await userEvent.keyboard("{Enter}");
      const skip = screen.getByRole("button", { name: "Pular" }) as HTMLButtonElement;
      expect(skip.disabled).toBe(true);
      await userEvent.keyboard("s");
      await act(async () => release(new Response(JSON.stringify({ previous: null, rule_id: null }), { status: 200 })));
      expect(await screen.findByText("Padaria Pão Bom")).toBeTruthy();
      expect(screen.getByText("2 de 3")).toBeTruthy();
    });

    it("undoing a confirmation that created a rule says the rule stays", async () => {
      setup([A, B], (url) => (url.endsWith("/confirm") ? json({ previous: null, rule_id: "r1" }) : undefined));
      await screen.findByText("Pessoa B Exemplo");
      await userEvent.click(screen.getByRole("switch", { name: /Sempre usar para/ }));
      await userEvent.keyboard("{Enter}");
      await screen.findByText("Classificado como Moradia · regra criada");
      await userEvent.keyboard("u");
      expect(await screen.findByText("Classificação desfeita · A regra continua ativa")).toBeTruthy();
    });
  });

  it("the note placeholder has no example", async () => {
    setup([B]);
    await screen.findByText("Padaria Pão Bom");
    expect(screen.getByRole("textbox", { name: "Nota" }).getAttribute("placeholder")).toBe("Nota (opcional)");
  });

  it("a transfer-detector suggestion is pre-selected with its reason", async () => {
    setup([item("t", { category_id: "own_transfer", source: "transfer_detector",
                       suggestion: { category_id: "own_transfer", reason: "transfer", detail: "Detectado como transferência" } })]);
    expect(await screen.findByText("Detectado como transferência")).toBeTruthy();
    expect(screen.getAllByRole("button", { pressed: true }).map((c) => c.textContent)).toEqual(["🔁 Transferência entre contas"]);
  });

  it("a low-confidence current category is pre-selected with its reason", async () => {
    setup([item("c", { category_id: "education", source: "pluggy_map",
                       suggestion: { category_id: "education", reason: "current", detail: "Categoria atual (confiança baixa)" } })]);
    expect(await screen.findByText("Categoria atual (confiança baixa)")).toBeTruthy();
    expect(screen.getAllByRole("button", { pressed: true }).map((c) => c.textContent)).toEqual(["🎓 Educação"]);
  });
});
