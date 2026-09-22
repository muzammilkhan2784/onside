import { useState, type ReactNode } from "react";
import clsx from "clsx";
import type { PassNetwork, Shot } from "../lib/types";

/**
 * A StatsBomb pitch: 120 x 80, origin top-left, the acting side attacking
 * left to right. Markings to regulation: 18-yard box 44 wide by 18 deep,
 * 6-yard box 20 by 6, penalty spot 12 out, centre circle radius 10.
 * Everything else draws on top of this; get the geometry right once.
 */
export function Pitch({ children, half = false, className = "" }: { children?: ReactNode; half?: boolean; className?: string }) {
  const L = "#4E8566";
  const vb = half ? "59 -1 62 82" : "-1 -1 122 82";
  return (
    <svg viewBox={vb} className={clsx("block h-auto w-full rounded-xl bg-pitch", className)} role="img">
      {/* mowing stripes, twelve of them, ten yards each */}
      {Array.from({ length: 12 }, (_, i) => i % 2 === 0 && (
        <rect key={i} x={i * 10} y={0} width={10} height={80} fill="#ffffff" opacity={0.025} />
      ))}
      <g fill="none" stroke={L} strokeWidth={0.5}>
        <rect x={0} y={0} width={120} height={80} />
        <line x1={60} y1={0} x2={60} y2={80} />
        <circle cx={60} cy={40} r={10} />
        <rect x={0} y={18} width={18} height={44} /><rect x={102} y={18} width={18} height={44} />
        <rect x={0} y={30} width={6} height={20} /><rect x={114} y={30} width={6} height={20} />
        <path d="M18 32.7 A10 10 0 0 1 18 47.3" /><path d="M102 32.7 A10 10 0 0 0 102 47.3" />
        <rect x={-1} y={36} width={1} height={8} /><rect x={120} y={36} width={1} height={8} />
      </g>
      <g fill={L}><circle cx={60} cy={40} r={0.6} /><circle cx={12} cy={40} r={0.6} /><circle cx={108} cy={40} r={0.6} /></g>
      {children}
    </svg>
  );
}

const HOME = "#5CC8FF", AWAY = "#FF5A6E", SIGNAL = "#FFC53D";

/** Every shot, both sides attacking the right-hand goal so they compare
 *  directly. Circle area scales with xG; filled circles were goals. */
export function ShotMap({ shots }: { shots: Shot[] }) {
  const inPlay = shots.filter((s) => !s.shootout);
  const [sel, setSel] = useState<string | null>(null);
  const [side, setSide] = useState<"both" | "home" | "away">("both");
  const shown = inPlay.filter((s) => side === "both" || (side === "home") === s.home);
  const selected = inPlay.find((s) => s.id === sel) ?? null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Which side">
        {(["both", "home", "away"] as const).map((s) => (
          <button key={s} onClick={() => setSide(s)} aria-pressed={side === s}
            className={clsx("chip", side === s && "border-chalk text-chalk")}>{s === "both" ? "Both sides" : s}</button>
        ))}
      </div>
      <Pitch half>
        {selected?.freeze.map((a, i) => (
          <g key={i}>
            <circle cx={a.x} cy={a.y} r={1.3}
              fill={a.keeper ? "#F2F6F0" : a.teammate ? (selected.home ? HOME : AWAY) : "#9DB2A4"} opacity={0.95} />
          </g>
        ))}
        {selected && (
          <>
            <line x1={selected.x} y1={selected.y} x2={selected.endX ?? 120} y2={selected.endY ?? 40}
              stroke={selected.goal ? "#2FCB74" : "#F2F6F0"} strokeWidth={0.35} strokeDasharray="1 0.8" />
            {/* the shooter's view of goal: posts at y=36 and y=44 */}
            <polygon points={`${selected.x},${selected.y} 120,36 120,44`} fill="#2FCB74" opacity={0.08} />
          </>
        )}
        {shown.map((s) => {
          const r = 0.9 + Math.sqrt(Math.max(s.xg ?? 0.01, 0.01)) * 3.6;
          const col = s.home ? HOME : AWAY;
          const isSel = s.id === sel;
          return (
            <circle key={s.id} cx={s.x} cy={s.y} r={r}
              fill={s.goal ? col : "transparent"} fillOpacity={s.goal ? 0.75 : 0}
              stroke={s.disallowed ? SIGNAL : col} strokeWidth={isSel ? 0.8 : 0.4}
              strokeDasharray={s.disallowed ? "0.8 0.6" : undefined}
              opacity={sel && !isSel ? 0.35 : 1}
              className="cursor-pointer transition-opacity" tabIndex={0} role="button"
              aria-label={`${s.player}, ${s.minute}', ${s.outcome}, xG ${(s.xg ?? 0).toFixed(2)}`}
              onClick={() => setSel(isSel ? null : s.id)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setSel(isSel ? null : s.id); }}>
              <title>{`${s.player} ${s.minute}' - xG ${(s.xg ?? 0).toFixed(2)} - ${s.outcome}`}</title>
            </circle>
          );
        })}
      </Pitch>
      <div className="min-h-[3.2rem] text-[13px] text-mute" aria-live="polite">
        {selected ? (
          <p>
            <b className="text-chalk">{selected.player}</b>, {selected.minute}' — {selected.type.toLowerCase()}, {selected.bodyPart.toLowerCase()}
            {selected.technique && selected.technique !== "Normal" ? `, ${selected.technique.toLowerCase()}` : ""}.
            Worth <b className="text-chalk num">{(selected.xg ?? 0).toFixed(2)}</b> expected goals — {selected.goal ? <b className="text-signal">scored</b> : selected.outcome.toLowerCase()}.{" "}
            {selected.disallowed && <b className="text-signal">Later disallowed. </b>}
            {selected.freeze.length
              ? <>The dots are the <b className="text-chalk">{selected.freeze.length}</b> players StatsBomb recorded around the ball at that instant; white is the keeper.</>
              : "No freeze-frame for this one - penalties have no defensive shape to capture."}
          </p>
        ) : (
          <p>Tap a shot to see where everyone stood when it was taken. Circle size is expected goals; filled circles went in; dashed amber rings were goals later disallowed.</p>
        )}
      </div>
    </div>
  );
}

export function PassNetworkView({ net, home }: { net: PassNetwork; home: boolean }) {
  const col = home ? HOME : AWAY;
  const nodes = new Map(net.nodes.map((n) => [n.id, n]));
  const maxPasses = Math.max(1, ...net.edges.map((e) => e.passes));
  const maxTouches = Math.max(1, ...net.nodes.map((n) => n.touches));
  if (!net.nodes.length) {
    return <p className="text-[13px] text-mute">Not enough completed passes between starters to draw a network for this side.</p>;
  }
  return (
    <div className="space-y-2">
      <Pitch>
        {net.edges.map((e) => {
          const a = nodes.get(e.a), b = nodes.get(e.b);
          if (!a || !b) return null;
          return <line key={`${e.a}-${e.b}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={col}
            strokeOpacity={0.15 + 0.7 * (e.passes / maxPasses)} strokeWidth={0.3 + 2.2 * (e.passes / maxPasses)} strokeLinecap="round" />;
        })}
        {net.nodes.map((n) => (
          <g key={n.id}>
            <circle cx={n.x} cy={n.y} r={1.6 + 2.4 * (n.touches / maxTouches)} fill="#06100B" stroke={col} strokeWidth={0.6} />
            <text x={n.x} y={n.y - 4.2} textAnchor="middle" fontSize={2.6} fill="#F2F6F0" fontFamily="Manrope, sans-serif" fontWeight={700}>
              {n.name.split(" ").slice(-1)[0]}
            </text>
          </g>
        ))}
      </Pitch>
      <p className="text-[12px] text-dim">{net.note} Line weight is passes between the pair; circle size is involvement. Average positions, attacking left to right.</p>
    </div>
  );
}
