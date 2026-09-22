import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Crest, FormationPitch, initials, kitFor, ReplayBadge } from "./Football";
import { FixtureRow, StoryCard } from "./MatchCard";
import type { LineupPlayer, MatchCard } from "../lib/types";

const FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true };

describe("crests", () => {
  it("abbreviates the way a scores app does, ignoring FC and friends", () => {
    expect(initials("Barcelona")).toBe("BAR");
    expect(initials("Manchester City WFC")).toBe("MC");
    expect(initials("Real Madrid")).toBe("RM");
    expect(initials("Deportivo Alavés")).toBe("DA");
    expect(initials("AFC Bournemouth")).toBe("BOU");
    expect(initials("England Women's")).toBe("ENG");
  });

  it("gives a team the same colours on every page", () => {
    expect(kitFor("Argentina")).toEqual(kitFor("Argentina"));
    const { container: a } = render(<Crest name="France" />);
    const { container: b } = render(<Crest name="France" />);
    expect(a.innerHTML).toBe(b.innerHTML);
  });
});

describe("the replay badge", () => {
  it("never reads as live - it says replay, and says when a replay is over", () => {
    render(<><ReplayBadge minute={67} /><ReplayBadge status="finished" /><ReplayBadge status="stopped" /></>);
    expect(screen.getByText(/Replay · 67'/)).toBeDefined();
    expect(screen.getByText("Replay ended")).toBeDefined();
    expect(screen.getByText("Replay stopped")).toBeDefined();
    expect(screen.queryByText(/live/i)).toBeNull();
  });
});

const card = (over: Partial<MatchCard> = {}): MatchCard => ({
  id: "3869685", competition: { id: "43", name: "FIFA World Cup" }, season: { id: "106", name: "2022" },
  date: "2022-12-18", kickoff: "16:00", stage: "Final", matchWeek: 7,
  home: { id: "779", name: "Argentina" }, away: { id: "771", name: "France" },
  score: [3, 3], shootout: [4, 2], status: "finished", xg: [3.1, 2.3],
  headline: "Argentina win it on penalties", standfirst: "A final for the ages.", tags: ["penalties"],
  biggestSwing: 0.4, hasFreezeFrames: true, live: false, ...over,
});

describe("match cards", () => {
  it("show a finished match as full time, with the date it was played", () => {
    render(<MemoryRouter future={FUTURE}><StoryCard card={card()} /></MemoryRouter>);
    expect(screen.getByText("Pens")).toBeDefined();
    expect(screen.getByText("18 Dec 2022")).toBeDefined();
    expect(screen.queryByText(/replay/i)).toBeNull();
  });

  it("mark a replay as a replay, not as a match being played today", () => {
    render(<MemoryRouter future={FUTURE}><StoryCard card={card({ id: "live-3869685", live: true })} /></MemoryRouter>);
    expect(screen.getByText("Replay")).toBeDefined();
  });

  it("put the penalty result under the score in a fixture row", () => {
    render(<MemoryRouter future={FUTURE}><FixtureRow card={card()} focusTeam="779" /></MemoryRouter>);
    expect(screen.getByText("4–2 p")).toBeDefined();
    expect(screen.getByText("W")).toBeDefined(); // won the shootout, so a win for Argentina
  });
});

describe("the formation pitch", () => {
  const xi = (prefix: string): LineupPlayer[] => [
    "Goalkeeper", "Right Back", "Right Center Back", "Left Center Back", "Left Back",
    "Right Defensive Midfield", "Left Defensive Midfield", "Right Wing", "Center Attacking Midfield", "Left Wing", "Center Forward",
  ].map((position, i) => ({ id: `${prefix}${i}`, name: `Player ${prefix}${i}`, number: i + 1, position, started: true, country: "" }));

  it("draws both starting elevens and leaves the bench off the pitch", () => {
    const bench: LineupPlayer = { id: "sub", name: "Bench Warmer", number: 23, position: "Substitute", started: false, country: "" };
    const { container } = render(<FormationPitch home={[...xi("h"), bench]} away={xi("a")} homeName="Argentina" awayName="France" />);
    expect(container.querySelectorAll("g[transform]")).toHaveLength(22);
    expect(screen.queryByText("Warmer")).toBeNull();
  });
});
