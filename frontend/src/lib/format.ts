const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** 2022-12-18 -> "18 December 2022". Parsed by hand: `new Date("2022-12-18")`
 *  is UTC midnight and renders as the 17th west of Greenwich. */
export function longDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
}

export function shortDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1].slice(0, 3)} ${m[1]}`;
}

export function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  return `${(v * 100).toFixed(digits)}%`;
}

export function num(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  return v.toFixed(digits);
}

export function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1000)}K`;
  return n.toLocaleString("en-GB");
}

export function ordinal(n: number): string {
  const r = n % 100;
  if (r >= 11 && r <= 13) return `${n}th`;
  return `${n}${({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th"}`;
}

/** "Lionel Andrés Messi Cuccittini" is correct and unreadable on a card. The
 *  API sends nicknames where StatsBomb records one; this is the fallback. */
export function shortName(name: string): string {
  const parts = name.split(" ");
  return parts.length <= 2 ? name : `${parts[0]} ${parts[parts.length - 1]}`;
}

export const TAG_LABEL: Record<string, string> = {
  turnaround: "Big swing",
  penalties: "Penalties",
  "goal-fest": "Goal-fest",
  "smash-and-grab": "Smash & grab",
  stalemate: "Stalemate",
  knockout: "Knockout",
};

export function scoreline(score: [number, number], shootout?: [number, number] | null): string {
  return `${score[0]}-${score[1]}${shootout ? ` (${shootout[0]}-${shootout[1]} pens)` : ""}`;
}
