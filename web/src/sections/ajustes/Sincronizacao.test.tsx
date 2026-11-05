import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Sincronizacao } from "./Sincronizacao";
import { mockApi, renderWithApp } from "./testutil";

const idle = { running: false, step: null, started_at: null, finished_at: null, report: null, runs: [], items: [
  { name: "Itaú", last_updated_at: "2026-10-30T12:00:00Z", status: "UPDATED" },
], binance_snapshot_at: "2026-10-31T08:00:00Z" };
const report = { warnings: ["no price for OPN on 1 days"], errors: ["Sincronização: boom"], counts: { pluggy: null, binance: null, classified: null } };

describe("Sincronização", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists the sources with their last update", async () => {
    mockApi((url) => (url.includes("/sync/status") ? idle : undefined));
    renderWithApp(<Sincronizacao />);
    expect(await screen.findByText("Itaú")).toBeTruthy();
    expect(screen.getByText(/atualizado 30\/10\/2026/)).toBeTruthy();
    expect(screen.getByText("Binance")).toBeTruthy();
  });

  it("disables the button while running, polls every tick, shows the step, then the result, and invalidates everything", async () => {
    let polls = 0;
    const calls = mockApi((url, { method }) => {
      if (method === "POST" && url.endsWith("/sync")) return new Response(JSON.stringify({ started: true }), { status: 202 });
      if (url.includes("/sync/status")) {
        if (polls === 0) { polls++; return idle; }
        polls++;
        if (polls < 4) return { ...idle, running: true, step: "pluggy" };
        return { ...idle, running: false, finished_at: "x", report };
      }
    });
    const { invalidate } = renderWithApp(<Sincronizacao pollMs={20} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Sincronizar agora" }));
    const posts = calls.filter((c) => c.method === "POST");
    expect(posts).toHaveLength(1);
    expect(posts[0].url).toBe("/api/v1/sync");
    const busy = await screen.findByRole("button", { name: /Sincronizando/ });
    expect((busy as HTMLButtonElement).disabled).toBe(true);
    expect(await screen.findByText(/Etapa: pluggy/)).toBeTruthy();
    expect(await screen.findByText(/no price for OPN/)).toBeTruthy();
    expect(screen.getByText(/Sincronização: boom/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Sincronizar agora" }) as HTMLButtonElement).disabled).toBe(false);
    // invalidateQueries() with no filter = all queries
    expect(invalidate.mock.calls.some((c) => c[0] === undefined)).toBe(true);
  });

  it("keeps polling a run started elsewhere and invalidates when it ends", async () => {
    let polls = 0;
    mockApi((url) => {
      if (!url.includes("/sync/status")) return undefined;
      polls++;
      return polls < 3 ? { ...idle, running: true, step: "classify" } : { ...idle, report: { warnings: [], errors: [], counts: {} } };
    });
    const { invalidate } = renderWithApp(<Sincronizacao pollMs={20} />);
    const busy = await screen.findByRole("button", { name: /Sincronizando/ });
    expect((busy as HTMLButtonElement).disabled).toBe(true);
    await waitFor(() => expect((screen.getByRole("button", { name: "Sincronizar agora" }) as HTMLButtonElement).disabled).toBe(false));
    expect(invalidate.mock.calls.some((c) => c[0] === undefined)).toBe(true);
  });

  it("does not invalidate everything when nothing was running", async () => {
    mockApi((url) => (url.includes("/sync/status") ? idle : undefined));
    const { invalidate } = renderWithApp(<Sincronizacao pollMs={20} />);
    await screen.findByText("Itaú");
    expect(invalidate.mock.calls.some((c) => c[0] === undefined)).toBe(false);
  });

  it("shows the API message on 409", async () => {
    mockApi((url, { method }) => {
      if (method === "POST") return new Response(JSON.stringify({ error: "Uma sincronização já está em andamento.", code: "sync_running" }), { status: 409 });
      if (url.includes("/sync/status")) return idle;
    });
    renderWithApp(<Sincronizacao />);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Sincronizar agora" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Uma sincronização já está em andamento.");
  });
});
