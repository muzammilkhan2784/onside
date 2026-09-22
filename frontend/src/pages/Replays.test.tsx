import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Replays from "./Replays";

const FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true };

function serve(features: object) {
  const asked: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    asked.push(url);
    const body = url.endsWith("/api/features") ? features : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter future={FUTURE}><Replays /></MemoryRouter>
    </QueryClientProvider>,
  );
  return asked;
}

afterEach(() => vi.unstubAllGlobals());

describe("the replay room", () => {
  it("on the free tier, says replays are off and never calls the replay service", async () => {
    const asked = serve({ realtime: false, replays: false, current: true, deployment: "free-tier" });
    expect(await screen.findByText(/Replays are switched off on this copy of Onside/)).toBeTruthy();
    expect(screen.queryByText(/Start the replay/)).toBeNull();
    expect(asked.some((u) => u.includes("/api/replay"))).toBe(false);
  });

  it("on the full deployment, offers replays", async () => {
    const asked = serve({ realtime: true, replays: true, current: true, deployment: "full" });
    expect(await screen.findByText(/Start the replay/)).toBeTruthy();
    await waitFor(() => expect(asked.some((u) => u.includes("/api/replay/status"))).toBe(true));
  });
});
