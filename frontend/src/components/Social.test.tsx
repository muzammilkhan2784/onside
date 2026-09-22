import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ago, Linkified, PostCard, SourceList } from "./Social";
import type { SocialOverview, SocialPost } from "../lib/types";

const FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true };

const post = (over: Partial<SocialPost> = {}): SocialPost => ({
  id: "bluesky:1", network: "bluesky", url: "https://bsky.app/profile/fan.bsky.social/post/3abc",
  author: { name: "A Fan", handle: "@fan.bsky.social", avatar: "", url: "https://bsky.app/profile/fan.bsky.social" },
  text: "What a goal! https://example.com/clip", createdAt: "2026-09-22T10:00:00Z", ts: Date.now() / 1000 - 120,
  lang: "en", metrics: { likes: 4, reposts: 1, replies: 2 }, media: [], topics: [], via: "", ...over,
});

describe("posts", () => {
  it("credit the author and link to the original", () => {
    render(<MemoryRouter future={FUTURE}><PostCard post={post()} /></MemoryRouter>);
    expect(screen.getByText("A Fan")).toBeDefined();
    expect(screen.getByText("View on Bluesky ↗").closest("a")?.getAttribute("href")).toBe("https://bsky.app/profile/fan.bsky.social/post/3abc");
    expect(screen.getByText("2m")).toBeDefined();
  });

  it("render text as text - markup in a post can never become markup on the page", () => {
    const { container } = render(<Linkified text={'<img src=x onerror="alert(1)"> see https://evil.example/x'} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror="alert(1)">');
    const a = container.querySelector("a")!;
    expect(a.getAttribute("href")).toBe("https://evil.example/x");
    expect(a.getAttribute("rel")).toContain("nofollow");
  });

  it("count time the short way", () => {
    const now = 1_000_000_000_000;
    expect([ago(now / 1000 - 30, now), ago(now / 1000 - 600, now), ago(now / 1000 - 7200, now), ago(now / 1000 - 200000, now)])
      .toEqual(["now", "10m", "2h", "2d"]);
  });
});

describe("the sources panel", () => {
  it("explains a source that is off, instead of leaving an empty column", () => {
    const sources = {
      bluesky: { state: "on", message: "Searching Bluesky.", count: 12 },
      mastodon: { state: "error", message: "Last attempt failed.", count: null },
      reddit: { state: "needs_key", message: "Reddit approves every new API app by hand.", count: null },
      x: { state: "paid_off", message: "X has no free API.", count: null },
    } as SocialOverview["sources"];
    render(<SourceList sources={sources} />);
    expect(screen.getByText("Connected")).toBeDefined();
    expect(screen.getByText("Having trouble")).toBeDefined();
    expect(screen.getByText("Needs a key")).toBeDefined();
    expect(screen.getByText("Off - paid API")).toBeDefined();
    expect(screen.getByText(/Last run: 12 new/)).toBeDefined();
  });
});
