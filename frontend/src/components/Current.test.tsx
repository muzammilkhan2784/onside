import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { CurrentOff, FixtureList, headline } from "./Current";
import type { Fixture } from "../lib/types";

const FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true };
const H = 3600_000;
const NOW = Date.parse("2026-09-26T12:00:00Z");

const fx = (over: Partial<Fixture>): Fixture => ({
  id: "fd-1", source: "football-data", competition: { id: "2021", name: "Premier League", code: "PL" },
  kickoffUtc: new Date(NOW + 2 * H).toISOString(), status: "scheduled", matchday: 6, stage: "Regular Season",
  home: { id: "57", name: "Arsenal", code: "ARS" }, away: { id: "61", name: "Chelsea", code: "CHE" },
  score: [null, null], halfTime: [null, null], ...over,
});

describe("what leads the home page", () => {
  it("puts a live match first, whatever else is on", () => {
    const pick = headline([fx({ id: "a" }), fx({ id: "b", status: "live", score: [1, 0], competition: { id: "", name: "Eredivisie", code: "DED" } })], NOW);
    expect(pick?.why).toBe("live");
    expect(pick?.fixture.id).toBe("b");
  });

  it("otherwise the next kick-off - the bigger competition within the next two days", () => {
    const pick = headline([
      fx({ id: "ded", kickoffUtc: new Date(NOW + 1 * H).toISOString(), competition: { id: "", name: "Eredivisie", code: "DED" } }),
      fx({ id: "pl", kickoffUtc: new Date(NOW + 3 * H).toISOString() }),
      fx({ id: "far", kickoffUtc: new Date(NOW + 60 * H).toISOString(), competition: { id: "", name: "Champions League", code: "CL" } }),
    ], NOW);
    expect(pick).toEqual({ fixture: expect.objectContaining({ id: "pl" }), why: "next" });
  });

  it("and the latest result only when nothing is left to play - the bigger competition first", () => {
    const bsa = { id: "", name: "Campeonato Brasileiro Série A", code: "BSA" };
    const pick = headline([
      fx({ id: "pl", status: "finished", score: [2, 1], kickoffUtc: new Date(NOW - 20 * H).toISOString() }),
      fx({ id: "bsa", status: "finished", score: [0, 0], kickoffUtc: new Date(NOW - 3 * H).toISOString(), competition: bsa }),
      fx({ id: "ancient", status: "finished", score: [9, 0], kickoffUtc: new Date(NOW - 80 * H).toISOString() }),
    ], NOW);
    expect(pick).toEqual({ fixture: expect.objectContaining({ id: "pl" }), why: "result" });
  });

  it("is nothing at all when there is no football - never an old match dressed up", () => {
    expect(headline([], NOW)).toBeNull();
  });
});

describe("fixture lists", () => {
  it("mark a real match in play as live, with its score", () => {
    render(<MemoryRouter future={FUTURE}><FixtureList matches={[fx({ status: "live", score: [1, 0] })]} /></MemoryRouter>);
    expect(screen.getByText("LIVE")).toBeDefined();
    expect(screen.getByText("1–0")).toBeDefined();
  });

  it("show 'vs' and a time, not a score, before kick-off", () => {
    render(<MemoryRouter future={FUTURE}><FixtureList matches={[fx({})]} /></MemoryRouter>);
    expect(screen.getByText("vs")).toBeDefined();
    expect(screen.queryByText("LIVE")).toBeNull();
  });

  it("link a followed match to what people are saying about it", () => {
    render(<MemoryRouter future={FUTURE}><FixtureList matches={[fx({})]} buzz={{ "fd-1": 12 }} /></MemoryRouter>);
    expect(screen.getByRole("link").getAttribute("href")).toBe("/buzz?topic=fd-1");
    expect(screen.getByText("💬 12")).toBeDefined();
  });
});

describe("when current fixtures are off", () => {
  it("says so plainly, and why, instead of an empty list", () => {
    render(<MemoryRouter future={FUTURE}><CurrentOff data={{ enabled: false, matches: [], message: "Set FOOTBALL_DATA_API_KEY to switch them on." }} /></MemoryRouter>);
    expect(screen.getByText("Current fixtures are switched off here.")).toBeDefined();
    expect(screen.getByText(/FOOTBALL_DATA_API_KEY/)).toBeDefined();
  });
});
