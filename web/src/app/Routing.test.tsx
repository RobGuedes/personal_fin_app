import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route } from "react-router";
import { ToastProvider } from "../components/Toast";
import { AppRoutes } from "./App";

function Boom(): never {
  throw new Error("render failed");
}

function setup(path: string, extra?: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {}))); // pages stay loading: no fake data
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes extra={extra} />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("routing", () => {
  it("a page that throws shows a pt-BR error inside the shell; the nav still works", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    setup("/boom", <Route path="boom" element={<Boom />} />);
    expect(screen.getByRole("alert").textContent).toContain("Esta tela encontrou um erro");
    expect(screen.getByRole("button", { name: "Recarregar" })).toBeTruthy();
    await userEvent.setup().click(screen.getAllByRole("link", { name: "Ajustes" })[0]);
    expect(screen.queryByText(/Esta tela encontrou um erro/)).toBeNull();
  });

  it("an unknown URL shows a not-found page with a way home, not a loading placeholder", () => {
    setup("/nao-existe");
    expect(screen.getByRole("heading", { name: "Página não encontrada" })).toBeTruthy();
    expect(screen.queryByText("Carregando…")).toBeNull();
    expect(screen.getByRole("link", { name: "Voltar ao Início" }).getAttribute("href")).toBe("/");
  });
});
