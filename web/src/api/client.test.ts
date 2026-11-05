import { ApiError, api } from "./client";

function mockFetch(res: Response) {
  const fn = vi.fn(async (_url: string, _init?: RequestInit) => res);
  vi.stubGlobal("fetch", fn);
  return fn;
}
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const headersOf = (fn: ReturnType<typeof mockFetch>) => fn.mock.calls[0][1]!.headers as Headers;

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("non-GET sends X-Finance-Client and JSON content type", async () => {
    const fn = mockFetch(json({ ok: true }));
    await api("/rules", { method: "POST", body: "{}" });
    expect(fn.mock.calls[0][0]).toBe("/api/v1/rules");
    expect(headersOf(fn).get("X-Finance-Client")).toBe("web");
    expect(headersOf(fn).get("Content-Type")).toBe("application/json");
  });

  it("GET does not add mutation headers", async () => {
    const fn = mockFetch(json({ ok: true }));
    expect(await api("/health")).toEqual({ ok: true });
    expect(headersOf(fn).get("X-Finance-Client")).toBeNull();
  });

  it("maps {error} to ApiError", async () => {
    mockFetch(json({ error: "regra inválida" }, 422));
    const err = await api("/rules", { method: "POST" }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 422, message: "regra inválida" });
  });
});
