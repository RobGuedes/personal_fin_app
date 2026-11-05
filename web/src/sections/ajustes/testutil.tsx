import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import type { ReactElement } from "react";
import { ToastProvider } from "../../components/Toast";

export interface Call { url: string; method: string; body: unknown }
type Handler = (url: string, init: { method: string; body: unknown }) => unknown | Response | undefined;

/** Stubs fetch with `handler` (return a Response, or a JSON value for 200; undefined = 404) and records every call. */
export function mockApi(handler: Handler) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = (init.method ?? "GET").toUpperCase();
    const body = init.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    const out = handler(url, { method, body });
    if (out instanceof Response) return out;
    if (out === undefined) return new Response(JSON.stringify({ error: "x", code: "nf" }), { status: 404 });
    return new Response(JSON.stringify(out), { status: 200 });
  }));
  return calls;
}

export function renderWithApp(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  const view = render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { qc, invalidate, ...view };
}
