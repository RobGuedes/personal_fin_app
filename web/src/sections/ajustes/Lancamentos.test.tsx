import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Lancamentos } from "./Lancamentos";
import { mockApi, renderWithApp } from "./testutil";

const entries = [{ id: 7, month: "2026-09", pnl_line: "income", pnl_line_label: "1. Renda", amount: 1500.5, note: "Bônus" }];

function api(onPost?: () => Response) {
  return mockApi((url, { method }) => {
    if (method === "POST") return onPost ? onPost() : new Response(JSON.stringify({ ...entries[0], id: 8 }), { status: 201 });
    if (method === "DELETE") return new Response(null, { status: 204 });
    if (url.endsWith("/manual-entries")) return entries;
  });
}

async function fill(user: ReturnType<typeof userEvent.setup>, v: { month?: string; line?: string; amount?: string; note?: string }) {
  if (v.month !== undefined) { await user.clear(screen.getByLabelText("Mês (AAAA-MM)")); await user.type(screen.getByLabelText("Mês (AAAA-MM)"), v.month); }
  if (v.line) await user.selectOptions(screen.getByLabelText("Linha do resultado"), v.line);
  if (v.amount !== undefined) await user.type(screen.getByLabelText("Valor"), v.amount);
  if (v.note !== undefined) await user.type(screen.getByLabelText("Descrição"), v.note);
}

describe("Lançamentos manuais", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists entries", async () => {
    api();
    renderWithApp(<Lancamentos />);
    expect(await screen.findByText("Bônus")).toBeTruthy();
    expect(screen.getByText("1. Renda")).toBeTruthy();
    expect(screen.getByText("R$ 1.500,50")).toBeTruthy();
  });

  it("validates client-side before calling the API", async () => {
    const calls = api();
    renderWithApp(<Lancamentos />);
    const user = userEvent.setup();
    await screen.findByText("Bônus");
    await fill(user, { month: "2026-13", line: "income", amount: "0", note: " " });
    await user.click(screen.getByRole("button", { name: "Adicionar lançamento" }));
    expect(screen.getByText("Mês inválido: use AAAA-MM.")).toBeTruthy();
    expect(screen.getByText("O valor deve ser um número diferente de zero.")).toBeTruthy();
    expect(screen.getByText("Informe uma descrição.")).toBeTruthy();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("posts a valid entry (pt-BR amount, trimmed note) and refreshes", async () => {
    const calls = api();
    const { invalidate } = renderWithApp(<Lancamentos />);
    const user = userEvent.setup();
    await screen.findByText("Bônus");
    await fill(user, { month: "2026-10", line: "expenses", amount: "-1.234,56", note: "  Reforma  " });
    await user.click(screen.getByRole("button", { name: "Adicionar lançamento" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(1));
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ month: "2026-10", pnl_line: "expenses", amount: -1234.56, note: "Reforma" });
    await waitFor(() => expect(invalidate.mock.calls.some((c) => c[0] === undefined || (c[0] as { queryKey?: string[] })?.queryKey?.[0] === "summary")).toBe(true));
  });

  it("shows the API's 422 message", async () => {
    api(() => new Response(JSON.stringify({ error: "Linha do resultado inválida.", code: "invalid_pnl_line" }), { status: 422 }));
    renderWithApp(<Lancamentos />);
    const user = userEvent.setup();
    await screen.findByText("Bônus");
    await fill(user, { month: "2026-10", line: "income", amount: "10", note: "x" });
    await user.click(screen.getByRole("button", { name: "Adicionar lançamento" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Linha do resultado inválida.");
  });

  it("deletes after an in-app confirmation", async () => {
    const calls = api();
    renderWithApp(<Lancamentos />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Excluir lançamento Bônus" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Excluir" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "DELETE").map((c) => c.url)).toEqual(["/api/v1/manual-entries/7"]));
  });
});
