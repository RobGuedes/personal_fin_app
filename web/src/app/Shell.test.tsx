import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router";
import { Shell } from "./Shell";
import { ToastProvider } from "../components/Toast";

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 })));
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/"]}>
          <Shell />
          <Where />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("Shell", () => {
  it("offers Ajustes in the sidebar and as a gear link with an accessible name in the phone header", async () => {
    setup();
    const links = screen.getAllByRole("link", { name: "Ajustes" });
    expect(links).toHaveLength(2);
    expect(document.querySelector(".phone-header a[aria-label='Ajustes']")).not.toBeNull();
    expect(document.querySelector(".sidebar a[href='/ajustes']")).not.toBeNull();
    await userEvent.setup().click(links[0]);
    expect(screen.getByTestId("where").textContent).toBe("/ajustes");
  });

  it("renders five nav items in pt-BR", () => {
    setup();
    const nav = screen.getAllByRole("navigation");
    expect(nav.length).toBeGreaterThan(0);
    for (const label of ["Início", "Revisar", "Transações", "Panorama", "Patrimônio"]) {
      expect(screen.getAllByRole("link", { name: new RegExp(label) }).length).toBeGreaterThan(0);
    }
  });

  it("g t goes to Transações", async () => {
    setup();
    const user = userEvent.setup();
    await user.keyboard("gt");
    expect(screen.getByTestId("where").textContent).toBe("/transacoes");
  });

  it("every nav item has an inline SVG icon drawn in currentColor", () => {
    setup();
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(12); // sidebar (+ Ajustes) + tab bar + phone gear
    for (const link of links) {
      const svg = link.querySelector("svg");
      expect(svg).not.toBeNull();
      expect(svg!.getAttribute("aria-hidden")).toBe("true");
      expect(svg!.getAttribute("stroke")).toBe("currentColor");
    }
    const firstFive = links.slice(0, 5).map((l) => l.querySelector("svg")!.innerHTML);
    expect(new Set(firstFive).size).toBe(5);
  });
});

describe("Shell sync watcher", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("refreshes every screen when a sync finishes, whatever page is open", async () => {
    const { waitFor } = await import("@testing-library/react");
    let polls = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (String(url).includes("/sync/status")) {
        polls++;
        return new Response(JSON.stringify({ running: polls < 3, runs: [], items: [] }), { status: 200 });
      }
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    render(
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <MemoryRouter initialEntries={["/"]}>
            <Shell syncPollMs={20} />
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(invalidate.mock.calls.some((c) => c[0] === undefined)).toBe(true));
    expect(invalidate.mock.calls.filter((c) => c[0] === undefined)).toHaveLength(1);
  });
});
