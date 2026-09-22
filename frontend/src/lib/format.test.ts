import { describe, expect, it } from "vitest";
import { compact, longDate, ordinal, pct, scoreline, shortDate, shortName } from "./format";

describe("dates", () => {
  it("formats without going through Date, which shifts the day west of Greenwich", () => {
    expect(longDate("2022-12-18")).toBe("18 December 2022");
    expect(shortDate("2022-12-18")).toBe("18 Dec 2022");
  });
  it("leaves anything it cannot parse alone", () => {
    expect(longDate("")).toBe("");
    expect(longDate("not a date")).toBe("not a date");
  });
});

describe("numbers", () => {
  it("shows a dash rather than NaN when a value is missing", () => {
    expect(pct(null)).toBe("-");
    expect(pct(undefined)).toBe("-");
    expect(pct(0.536)).toBe("54%");
  });
  it("compacts large counts", () => {
    expect(compact(13_911_986)).toBe("13.9M");
    expect(compact(3961)).toBe("3,961");
  });
  it("gets the awkward ordinals right", () => {
    expect([1, 2, 3, 11, 12, 13, 21, 22].map(ordinal))
      .toEqual(["1st", "2nd", "3rd", "11th", "12th", "13th", "21st", "22nd"]);
  });
});

describe("match helpers", () => {
  it("shortens long legal names but leaves normal ones", () => {
    expect(shortName("Lionel Andrés Messi Cuccittini")).toBe("Lionel Cuccittini");
    expect(shortName("Phil Foden")).toBe("Phil Foden");
  });
  it("marks a shootout in the scoreline", () => {
    expect(scoreline([3, 3], [4, 2])).toBe("3-3 (4-2 pens)");
    expect(scoreline([1, 0])).toBe("1-0");
  });
});
