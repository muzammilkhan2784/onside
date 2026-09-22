import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";

const ok = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));

afterEach(() => vi.unstubAllGlobals());

describe("the API client", () => {
  it("surfaces the server's own message, which is written for people", async () => {
    vi.stubGlobal("fetch", () => Promise.resolve(new Response(
      JSON.stringify({ error: "match_not_found", message: "There is no match 'x' in the archive.", detail: {} }),
      { status: 404 })));
    await expect(api.match("x")).rejects.toMatchObject({
      status: 404, code: "match_not_found", message: "There is no match 'x' in the archive.",
    });
  });

  it("explains a network failure instead of leaking a TypeError", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new TypeError("Failed to fetch")));
    const err = await api.home().catch((e) => e as ApiError);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toMatch(/could not be reached/);
  });

  it("copes with an error body that is not JSON", async () => {
    vi.stubGlobal("fetch", () => Promise.resolve(new Response("<html>502</html>", { status: 502 })));
    await expect(api.home()).rejects.toMatchObject({ status: 502, code: "http_error" });
  });

  it("omits empty query parameters rather than sending blanks", async () => {
    const seen: string[] = [];
    vi.stubGlobal("fetch", (url: string) => { seen.push(url); return ok({ items: [], next: null }); });
    await api.feed({ tag: undefined, cursor: null, limit: 24 });
    expect(seen[0]).toBe("/api/feed?limit=24");
  });

  it("sends replay commands as JSON", async () => {
    const calls: [string, RequestInit][] = [];
    vi.stubGlobal("fetch", (url: string, init: RequestInit) => { calls.push([url, init]); return ok({}); });
    await api.replayStart(3869685, 60, true);
    expect(calls[0][0]).toBe("/api/replay/start");
    expect(JSON.parse(String(calls[0][1].body))).toEqual({ match_id: 3869685, speed: 60, inject_var: true });
  });
});
