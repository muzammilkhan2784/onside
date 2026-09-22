import clsx from "clsx";
import type { LineupPlayer } from "../lib/types";

/**
 * Football primitives: crests, competition marks, the full-time pill and the
 * replay badge. Onside has no licence for club badges, so every crest is
 * generated - a shield in kit colours with the club's initials, derived from
 * the name so a team looks the same on every page.
 */

const KITS: [string, string, string][] = [
  // [primary, secondary, initials]
  ["#D7263D", "#FFFFFF", "#FFFFFF"],
  ["#1F5FBF", "#FFFFFF", "#FFFFFF"],
  ["#6CB4EE", "#14264F", "#14264F"],
  ["#F1F1EE", "#1A1A1A", "#1A1A1A"],
  ["#F5C400", "#1A1A1A", "#1A1A1A"],
  ["#1F8A4C", "#FFFFFF", "#FFFFFF"],
  ["#1C1C1C", "#E9E9E9", "#FFFFFF"],
  ["#7A1F3D", "#8FC6EA", "#FFFFFF"],
  ["#F07D00", "#1A1A1A", "#1A1A1A"],
  ["#1B2A5A", "#E6E6E6", "#FFFFFF"],
  ["#5B2C83", "#F5C400", "#FFFFFF"],
  ["#B31B1B", "#1A1A1A", "#FFFFFF"],
];

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

const NOISE = new Set(["fc", "cf", "afc", "sc", "ac", "cd", "ud", "sd", "rc", "wfc", "lfc", "women", "womens", "de", "of", "the", "club", "city's"]);

/** "Manchester City WFC" -> "MC", "Barcelona" -> "BAR", "Bayer Leverkusen" -> "BL". */
export function initials(name: string): string {
  const words = name.replace(/[.'’]/g, "").split(/[\s-]+/).filter((w) => w && !NOISE.has(w.toLowerCase()));
  if (!words.length) return name.slice(0, 3).toUpperCase();
  if (words.length === 1) return words[0].slice(0, 3).toUpperCase();
  return words.slice(0, 3).map((w) => w[0]).join("").toUpperCase();
}

export function kitFor(name: string): [string, string, string] {
  return KITS[hash(name) % KITS.length];
}

const SHIELD = "M12 1 L22.5 4.2 V13 C22.5 20 17.8 24.6 12 27 C6.2 24.6 1.5 20 1.5 13 V4.2 Z";

export function Crest({ name, code, size = 28, className = "" }: { name: string; code?: string; size?: number; className?: string }) {
  const h = hash(name);
  const [a, b, ink] = kitFor(name);
  const pattern = (h >>> 8) % 4; // plain, halves, sash, stripes
  const id = `c${h.toString(36)}`;
  const text = (code || initials(name)).slice(0, 3).toUpperCase();
  return (
    <svg width={size} height={size * (28 / 24)} viewBox="0 0 24 28" className={clsx("shrink-0", className)} aria-hidden>
      <defs><clipPath id={id}><path d={SHIELD} /></clipPath></defs>
      <g clipPath={`url(#${id})`}>
        <rect width="24" height="28" fill={a} />
        {pattern === 1 && <rect x="12" width="12" height="28" fill={b} opacity={0.9} />}
        {pattern === 2 && <path d="M-2 6 L26 26 L26 32 L-2 12 Z" fill={b} opacity={0.9} />}
        {pattern === 3 && [4, 12, 20].map((x) => <rect key={x} x={x - 1.6} width="3.2" height="28" fill={b} opacity={0.85} />)}
        <rect y="15" width="24" height="13" fill="#000" opacity={pattern === 0 ? 0 : 0.18} />
      </g>
      <path d={SHIELD} fill="none" stroke="#000" strokeOpacity={0.35} strokeWidth={0.8} />
      <text x="12" y={text.length > 2 ? 17.2 : 17.6} textAnchor="middle" fontFamily="Anton, Impact, sans-serif"
        fontSize={text.length > 2 ? 7.4 : 9} fill={pattern === 0 ? ink : "#FFFFFF"} stroke={pattern === 0 ? "none" : "#000"}
        strokeOpacity={0.35} strokeWidth={0.5} paintOrder="stroke" letterSpacing={0.2}>{text}</text>
    </svg>
  );
}

/** A small trophy-roundel for a competition, in its own stable colour. */
export function CompetitionMark({ name, size = 22 }: { name: string; size?: number }) {
  const [a] = kitFor(`comp:${name}`);
  return (
    <span className="grid shrink-0 place-items-center rounded-full border border-white/10"
      style={{ width: size, height: size, background: `radial-gradient(circle at 30% 30%, ${a}, #0A140E 90%)` }} aria-hidden>
      <svg width={size * 0.55} height={size * 0.55} viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <path d="M7 4h10v5a5 5 0 0 1-10 0V4Z" /><path d="M7 6H4a3 3 0 0 0 3 4M17 6h3a3 3 0 0 1-3 4M12 14v4M8 20h8" />
      </svg>
    </span>
  );
}

/** FT, FT + pens - the result line every scores app puts next to a score. */
export function FullTime({ shootout, className = "" }: { shootout?: [number, number] | null; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center rounded-md bg-chalk/10 px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider text-mute", className)}>
      {shootout ? "Pens" : "FT"}
    </span>
  );
}

/** Green, pulsing: a real match being played right now, from a live feed.
 *  Only football-data.org fixtures ever carry this - never a replay. */
export function LiveBadge({ label = "Live" }: { label?: string }) {
  return (
    <span className="chip border-live/50 text-live">
      <i className="h-1.5 w-1.5 animate-blip rounded-full bg-live" />{label}
    </span>
  );
}

/** Violet, circular arrow: this is a replay of a match that has been played. */
export function ReplayBadge({ minute, status = "running", className = "" }: { minute?: number; status?: string; className?: string }) {
  const playing = status === "running";
  const label = status === "idle" ? "Replays" : status === "paused" ? "Replay paused" : status === "finished" ? "Replay ended"
    : status === "stopped" ? "Replay stopped" : "Replay";
  return (
    <span className={clsx("chip border-replay/50 text-replay", className)}>
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6} strokeLinecap="round" aria-hidden
        className={playing ? "animate-[spin_3s_linear_infinite]" : ""}>
        <path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" />
      </svg>
      {label}{playing && minute !== undefined ? ` · ${minute}'` : ""}
    </span>
  );
}

export function Ball({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={clsx("inline-block h-3.5 w-3.5", className)} aria-hidden>
      <circle cx="12" cy="12" r="10" fill="#F2F6F0" />
      <path d="M12 7.2l4 2.9-1.5 4.7h-5L8 10.1z" fill="#06100B" />
      <path d="M12 2v5.2M16 10.1l5-1.6M14.5 14.8l3 4.3M9.5 14.8l-3 4.3M8 10.1L3 8.5" stroke="#06100B" strokeWidth={1.2} />
    </svg>
  );
}

export function Card({ colour }: { colour: "yellow" | "red" | "second" }) {
  return (
    <span className={clsx("inline-block h-3.5 w-2.5 rounded-[2px]",
      colour === "yellow" ? "bg-[#F5C400]" : colour === "red" ? "bg-[#E0263B]" : "bg-[linear-gradient(135deg,#F5C400_50%,#E0263B_50%)]")} aria-hidden />
  );
}

// ---- formation -------------------------------------------------------------

/** StatsBomb position name -> (depth from own goal line, left-to-right across
 *  the team's own view), both 0..100. Depth 100 is the halfway line. */
const SPOT: Record<string, [number, number]> = {
  "Goalkeeper": [8, 50],
  "Right Back": [34, 88], "Right Center Back": [28, 66], "Center Back": [27, 50], "Left Center Back": [28, 34], "Left Back": [34, 12],
  "Right Wing Back": [48, 90], "Left Wing Back": [48, 10],
  "Right Defensive Midfield": [46, 64], "Center Defensive Midfield": [45, 50], "Left Defensive Midfield": [46, 36],
  "Right Midfield": [62, 86], "Right Center Midfield": [58, 66], "Center Midfield": [58, 50], "Left Center Midfield": [58, 34], "Left Midfield": [62, 14],
  "Right Attacking Midfield": [72, 70], "Center Attacking Midfield": [72, 50], "Left Attacking Midfield": [72, 30],
  "Right Wing": [80, 86], "Left Wing": [80, 14],
  "Right Center Forward": [88, 62], "Striker": [90, 50], "Center Forward": [90, 50], "Left Center Forward": [88, 38], "Secondary Striker": [82, 50],
};

const lastName = (n: string) => { const p = n.split(" "); return p.length > 1 ? p[p.length - 1] : n; };

/** Both starting XIs on one vertical pitch, as a broadcast shows them before
 *  kick-off: home at the bottom attacking up, away at the top attacking down. */
export function FormationPitch({ home, away, homeName, awayName }:
  { home: LineupPlayer[]; away: LineupPlayer[]; homeName: string; awayName: string }) {
  const W = 68, H = 105, L = "#4E8566";
  const place = (p: LineupPlayer, top: boolean): [number, number] | null => {
    const s = SPOT[p.position];
    if (!s) return null;
    const [depth, lat] = s;
    const y = (depth / 100) * (H / 2);
    const x = (lat / 100) * W;
    // Home defends the bottom goal: its left is screen left. Away is mirrored.
    return top ? [W - x, y] : [x, H - y];
  };
  const side = (players: LineupPlayer[], top: boolean, colour: string, ink: string) =>
    players.filter((p) => p.started).map((p) => {
      const at = place(p, top);
      if (!at) return null;
      return (
        <g key={p.id} transform={`translate(${at[0]} ${at[1]})`}>
          <circle r={2.9} fill={colour} stroke="#000" strokeOpacity={0.4} strokeWidth={0.3} />
          <text y={1.05} textAnchor="middle" fontSize={2.6} fontWeight={800} fill={ink} fontFamily="Manrope, sans-serif">{p.number ?? ""}</text>
          <text y={top ? -3.9 : 5.6} textAnchor="middle" fontSize={2.3} fontWeight={700} fill="#F2F6F0"
            stroke="#06100B" strokeWidth={0.6} paintOrder="stroke" fontFamily="Manrope, sans-serif">{lastName(p.name)}</text>
        </g>
      );
    });
  return (
    <svg viewBox={`-2 -2 ${W + 4} ${H + 4}`} className="block h-auto w-full rounded-xl bg-pitch" role="img"
      aria-label={`Starting line-ups: ${homeName} at the bottom, ${awayName} at the top`}>
      {Array.from({ length: 10 }, (_, i) => i % 2 === 0 && <rect key={i} x={0} y={i * 10.5} width={W} height={10.5} fill="#fff" opacity={0.025} />)}
      <g fill="none" stroke={L} strokeWidth={0.4}>
        <rect x={0} y={0} width={W} height={H} />
        <line x1={0} y1={H / 2} x2={W} y2={H / 2} />
        <circle cx={W / 2} cy={H / 2} r={9.15} />
        <rect x={(W - 40.3) / 2} y={0} width={40.3} height={16.5} /><rect x={(W - 40.3) / 2} y={H - 16.5} width={40.3} height={16.5} />
        <rect x={(W - 18.3) / 2} y={0} width={18.3} height={5.5} /><rect x={(W - 18.3) / 2} y={H - 5.5} width={18.3} height={5.5} />
        <rect x={(W - 7.3) / 2} y={-1.4} width={7.3} height={1.4} /><rect x={(W - 7.3) / 2} y={H} width={7.3} height={1.4} />
      </g>
      {side(away, true, "#FF5A6E", "#2A0008")}
      {side(home, false, "#5CC8FF", "#001B2A")}
    </svg>
  );
}
