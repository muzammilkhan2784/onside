import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { LeagueTable, ReportView, Timeline } from "./MatchParts";
import type { MatchState, Report, Table } from "../lib/types";

const FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true };

const state = {
  id: "live-1",
  home: { id: "1", name: "Argentina", country: "", manager: "" },
  away: { id: "2", name: "France", country: "", manager: "" },
  glossary: {},
  timeline: [
    { kind: "goal", period: 1, minute: 22, second: 0, home: true, team: "Argentina", player: "Lionel Messi",
      detail: "Penalty", eventId: "g1", xg: 0.78 },
    { kind: "goal", period: 1, minute: 35, second: 0, home: true, team: "Argentina", player: "Ángel Di María",
      detail: "Open Play", eventId: "g2", xg: 0.3, disallowed: true, correctedAt: 37,
      correctionReason: "Handball in the build-up" },
    { kind: "correction", period: 1, minute: 37, second: 59, home: null, team: "", player: "",
      detail: "Handball in the build-up", eventId: "c1", correctionKind: "disallow", authority: "VAR",
      supersedes: "g2", synthesised: true },
  ],
} as unknown as MatchState;

describe("the timeline", () => {
  it("keeps a disallowed goal, struck through, with the reason and the minute", () => {
    render(<MemoryRouter future={FUTURE}><Timeline state={state} /></MemoryRouter>);
    const goal = screen.getByText("Ángel Di María");
    expect(goal.className).toContain("line-through");
    expect(screen.getByText(/ruled out at 37'/)).toHaveTextContent("Handball in the build-up");
  });

  it("names the authority and marks a synthesised decision as synthesised", () => {
    render(<MemoryRouter future={FUTURE}><Timeline state={state} /></MemoryRouter>);
    expect(screen.getByText("Goal disallowed")).toBeDefined();
    expect(screen.getByText("VAR")).toBeDefined();
    expect(screen.getByText("synthesised")).toBeDefined();
  });

  it("explains an empty timeline instead of showing nothing", () => {
    render(<MemoryRouter future={FUTURE}><Timeline state={{ ...state, timeline: [] } as MatchState} /></MemoryRouter>);
    expect(screen.getByText(/nothing is ever removed/i)).toBeDefined();
  });
});

describe("the report", () => {
  const report: Report = {
    headline: "Argentina 1-0 France", lede: "Argentina lead.",
    lines: ["22' - Lionel Messi converted the penalty to make it 1-0."],
    closing: "", notes: [], moments: [],
  };
  it("splits the minute out so lines align, and says it was written by rules", () => {
    render(<ReportView report={report} corrected={false} synthesised={false} />);
    expect(screen.getByText("22'")).toBeDefined();
    expect(screen.getByText(/not a language model/i)).toBeDefined();
  });
});

describe("the league table", () => {
  const table: Table = {
    group: "Group 1", ruleId: "FIFA_GROUP",
    explanation: "World Cup groups separate level teams on goal difference first.",
    note: "", unresolved: [],
    rows: [{ position: 1, teamId: "10", team: "Netherlands", played: 3, won: 2, drawn: 1, lost: 0,
             goalsFor: 5, goalsAgainst: 1, goalDifference: 4, points: 7 }],
  };
  it("shows the tie-break rule in words next to the table", () => {
    render(<MemoryRouter future={FUTURE}><LeagueTable table={table} /></MemoryRouter>);
    expect(screen.getByText(/goal difference first/)).toBeDefined();
    const row = screen.getByText("Netherlands").closest("tr")!;
    expect(within(row).getByText("+4")).toBeDefined();
    expect(within(row).getByText("7")).toBeDefined();
  });
});
