import { transacoesLink } from "./links";

describe("transacoesLink", () => {
  it("maps category and line, with the month when given and mes=todos (all months) otherwise", () => {
    expect(transacoesLink({ category: "restaurants" }, { month: "2026-10" })).toBe("/transacoes?mes=2026-10&categoria=restaurants");
    expect(transacoesLink({ category: "uncategorized", line: "expenses" })).toBe("/transacoes?mes=todos&categoria=uncategorized&linha=expenses");
    expect(transacoesLink({ line: "commissions" })).toBe("/transacoes?mes=todos&linha=commissions");
  });
});
