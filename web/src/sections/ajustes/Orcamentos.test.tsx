import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Orcamentos } from "./Orcamentos";
import { mockApi, renderWithApp } from "./testutil";

const taxonomy = {
  lines: [],
  categories: [
    { id: "groceries", line: "expenses", label: "Mercado", icon: "x", color_slot: 0 },
    { id: "fuel", line: "expenses", label: "Combustível", icon: "x", color_slot: 1 },
    { id: "salary", line: "income", label: "Salário", icon: "x", color_slot: null },
  ],
};
const panorama = {
  months: [], savings_rate: null, avg_income: 0, avg_spending: 0,
  categories: [
    { category_id: "groceries", label: "Mercado", total: 0, monthly_avg: 900, sparkline: [], usual: 1000 },
    { category_id: "fuel", label: "Combustível", total: 0, monthly_avg: 400, sparkline: [], usual: null },
  ],
};

function api(budgets: Record<string, number> = {}) {
  return mockApi((url, { method }) => {
    if (method === "PUT") return { ok: 1 };
    if (method === "DELETE") return new Response(null, { status: 204 });
    if (url.includes("/taxonomy")) return taxonomy;
    if (url.includes("/panorama?period=last12")) return panorama;
    if (url.endsWith("/budgets")) return budgets;
  });
}

describe("Orçamentos", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists expense categories only, pre-filled with usual (or monthly_avg) and shows usual", async () => {
    api();
    renderWithApp(<Orcamentos />);
    const groceries = (await screen.findByLabelText("Orçamento mensal de Mercado")) as HTMLInputElement;
    expect(groceries.value).toBe("1000");
    expect((screen.getByLabelText("Orçamento mensal de Combustível") as HTMLInputElement).value).toBe("400");
    expect(screen.queryByLabelText("Orçamento mensal de Salário")).toBeNull();
    expect(screen.getByText("usual R$ 1.000,00")).toBeTruthy();
  });

  it("a saved budget replaces the suggestion; editing PUTs and refreshes Início queries", async () => {
    const calls = api({ groceries: 1200 });
    const { invalidate } = renderWithApp(<Orcamentos />);
    const input = (await screen.findByLabelText("Orçamento mensal de Mercado")) as HTMLInputElement;
    expect(input.value).toBe("1200");
    const user = userEvent.setup();
    await user.clear(input);
    await user.type(input, "1500");
    await user.click(screen.getByRole("button", { name: "Salvar orçamento de Mercado" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.url).toBe("/api/v1/budgets/groceries");
    expect(put.body).toEqual({ monthly_amount: 1500 });
    await waitFor(() => expect(invalidate.mock.calls.some((c) => c[0] === undefined || (c[0] as { queryKey?: string[] })?.queryKey?.[0] === "summary")).toBe(true));
  });

  it("clearing a saved budget sends DELETE", async () => {
    const calls = api({ groceries: 1200 });
    renderWithApp(<Orcamentos />);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Remover orçamento de Mercado" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "DELETE").map((c) => c.url)).toEqual(["/api/v1/budgets/groceries"]));
  });

  it("rejects a non-positive value without calling the API", async () => {
    const calls = api();
    renderWithApp(<Orcamentos />);
    const input = await screen.findByLabelText("Orçamento mensal de Mercado");
    const user = userEvent.setup();
    await user.clear(input);
    await user.type(input, "0");
    await user.click(screen.getByRole("button", { name: "Salvar orçamento de Mercado" }));
    expect(await screen.findByText("Informe um valor maior que zero.")).toBeTruthy();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });
});
