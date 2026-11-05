import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Ajustes } from "./Ajustes";
import { mockApi, renderWithApp } from "./testutil";

const transfers = [{
  link_type: "own_transfer", link_label: "Transferência entre contas", confidence: 1, from_date: "2026-10-02", from_account: "Itaú ••12",
  from_description: "Pix enviado", from_amount: -500, to_date: "2026-10-02", to_account: "XP ••34", to_description: "Pix recebido", to_amount: 500,
}, {
  link_type: "investment_contribution", link_label: "Aplicação", confidence: 0.5, from_date: "2026-10-03", from_account: "BTG ••99",
  from_description: "Aplicação fundo", from_amount: -100, to_date: null, to_account: null, to_description: null, to_amount: null,
}];

describe("Ajustes", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders every section and the transfer audit with both legs", async () => {
    mockApi((url) => {
      if (url.endsWith("/transfers")) return transfers;
      if (url.includes("/sync/status")) return { running: false, runs: [], items: [], report: null, binance_snapshot_at: null };
      if (url.endsWith("/rules") || url.endsWith("/manual-entries")) return [];
      if (url.includes("/taxonomy")) return { lines: [], categories: [] };
      if (url.includes("/panorama")) return { months: [], categories: [] };
      if (url.endsWith("/budgets")) return {};
    });
    renderWithApp(<Ajustes />);
    expect(screen.getByRole("heading", { name: "Ajustes", level: 1 })).toBeTruthy();
    for (const h of ["Sincronização", "Auditoria de transferências", "Regras", "Orçamentos", "Lançamentos manuais", "Aparência"]) {
      expect(screen.getByRole("heading", { name: h })).toBeTruthy();
    }
    expect(await screen.findByText("Pix enviado")).toBeTruthy();
    expect(screen.getByText("Pix recebido")).toBeTruthy();
    expect(screen.getByText("Itaú ••12")).toBeTruthy();
    expect(screen.getByText("sem par (uma ponta só)")).toBeTruthy();
  });

  it("audit shows the 10 most recent and toggles to all", async () => {
    const many = Array.from({ length: 25 }, (_, i) => ({ ...transfers[0], from_description: `Pix n${i}` }));
    mockApi((url) => {
      if (url.endsWith("/transfers")) return many;
      if (url.includes("/sync/status")) return { running: false, runs: [], items: [], report: null, binance_snapshot_at: null };
      if (url.endsWith("/rules") || url.endsWith("/manual-entries")) return [];
      if (url.includes("/taxonomy")) return { lines: [], categories: [] };
      if (url.includes("/panorama")) return { months: [], categories: [] };
      if (url.endsWith("/budgets")) return {};
    });
    renderWithApp(<Ajustes />);
    expect(await screen.findByText("Pix n0")).toBeTruthy();
    expect(screen.queryByText("Pix n10")).toBeNull();
    const btn = screen.getByRole("button", { name: "Ver todas (25)" });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    await userEvent.setup().click(btn);
    expect(screen.getByText("Pix n24")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ver só as 10 mais recentes" }).getAttribute("aria-expanded")).toBe("true");
  });
});
