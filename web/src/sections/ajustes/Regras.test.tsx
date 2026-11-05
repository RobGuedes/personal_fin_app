import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Regras } from "./Regras";
import { mockApi, renderWithApp } from "./testutil";

const rules = [
  { id: "cliente_exterior", category_id: "services_abroad", category_label: "Serviços no exterior", conditions: { account: "Binance", direction: "in", amount_min: 1000 }, priority: 10 },
  { id: "ong", category_id: "donations", category_label: "Doações", conditions: { has_cnpj: true }, priority: 0 },
];

describe("Regras", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists rules with category chip and conditions; no document is shown", async () => {
    mockApi((url) => (url.endsWith("/rules") ? rules : undefined));
    renderWithApp(<Regras />);
    expect(await screen.findByText("cliente_exterior")).toBeTruthy();
    expect(screen.getByText("Serviços no exterior")).toBeTruthy();
    expect(screen.getByText(/Binance/)).toBeTruthy();
    expect(screen.getByText(/entrada/)).toBeTruthy();
    expect(screen.getByText(/CNPJ da contraparte/)).toBeTruthy();
  });

  it("asks for confirmation in an in-app dialog, then deletes and refreshes", async () => {
    const confirmSpy = vi.fn(() => true);
    vi.stubGlobal("confirm", confirmSpy);
    const calls = mockApi((url, { method }) => {
      if (method === "DELETE") return { ok: true };
      if (url.endsWith("/rules")) return rules;
    });
    const { invalidate } = renderWithApp(<Regras />);
    const user = userEvent.setup();
    const trigger = await screen.findByRole("button", { name: "Excluir regra cliente_exterior" });
    await user.click(trigger);
    const dialog = screen.getByRole("alertdialog");
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    expect(dialog.contains(document.activeElement)).toBe(true);
    await user.click(within(dialog).getByRole("button", { name: "Excluir" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "DELETE").map((c) => c.url)).toEqual(["/api/v1/rules/cliente_exterior"]));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(invalidate).toHaveBeenCalled();
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it("Esc cancels without deleting and focus returns to the trigger", async () => {
    const calls = mockApi((url) => (url.endsWith("/rules") ? rules : undefined));
    renderWithApp(<Regras />);
    const user = userEvent.setup();
    const trigger = await screen.findByRole("button", { name: "Excluir regra ong" });
    await user.click(trigger);
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  });

  it("shows the API error when deleting fails", async () => {
    mockApi((url, { method }) => {
      if (method === "DELETE") return new Response(JSON.stringify({ error: "Regra não encontrada.", code: "rule_not_found" }), { status: 404 });
      if (url.endsWith("/rules")) return rules;
    });
    renderWithApp(<Regras />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Excluir regra ong" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Excluir" }));
    expect(await screen.findByText("Regra não encontrada.")).toBeTruthy();
  });
});
