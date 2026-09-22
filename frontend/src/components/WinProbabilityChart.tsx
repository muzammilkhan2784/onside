import { Area, AreaChart, CartesianGrid, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Goal, WpPoint } from "../lib/types";

interface Props {
  series: WpPoint[];
  goals: Goal[];
  home: string;
  away: string;
  /** Cut the river at the live clock; the model's rows past it are not known yet. */
  upToMinute?: number;
}

const HOME = "#5CC8FF", AWAY = "#FF5A6E", DRAW = "#3C5A48", SIGNAL = "#FFC53D";

/**
 * The stacked win-probability river. Goals are marked; a goal that was later
 * disallowed gets a hatched band over the minutes it stood, so the chart shows
 * that the score *was* different - the thing no mutable scores site can show.
 */
export default function WinProbabilityChart({ series, goals, home, away, upToMinute }: Props) {
  const cut = upToMinute === undefined ? 90 : Math.min(upToMinute, 90);
  const data = series.filter((p) => p.minute <= cut).map((p) => ({
    minute: p.minute, home: p.p_home, draw: p.p_draw, away: p.p_away,
  }));
  if (data.length < 2) {
    return <p className="px-4 py-10 text-center text-[13px] text-mute">The chart starts drawing once the match is a minute old.</p>;
  }
  const reg = goals.filter((g) => g.period <= 2 && g.minute <= cut);
  return (
    <div className="h-64 w-full sm:h-72">
      <ResponsiveContainer>
        <AreaChart data={data} stackOffset="expand" margin={{ top: 12, right: 8, bottom: 0, left: -18 }}>
          <defs>
            <pattern id="hatch" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
              <rect width="6" height="6" fill="rgba(255,197,61,.10)" />
              <line x1="0" y1="0" x2="0" y2="6" stroke="rgba(255,197,61,.55)" strokeWidth="1.6" />
            </pattern>
          </defs>
          <CartesianGrid stroke="#1F3A2A" vertical={false} />
          <XAxis dataKey="minute" type="number" domain={[0, 90]} ticks={[0, 15, 30, 45, 60, 75, 90]}
            tickFormatter={(m) => `${m}'`} stroke="#647A6C" fontSize={10} tickLine={false} />
          <YAxis tickFormatter={(v) => `${Math.round(v * 100)}`} ticks={[0, 0.25, 0.5, 0.75, 1]} stroke="#647A6C" fontSize={10} tickLine={false} axisLine={false} />
          <Tooltip
            contentStyle={{ background: "#0C1A12", border: "1px solid #1F3A2A", borderRadius: 10, fontSize: 12, color: "#F2F6F0" }}
            labelFormatter={(m) => `${m}'`}
            formatter={(v: number, k: string) => [`${Math.round(v * 100)}%`, k === "home" ? `${home} win` : k === "away" ? `${away} win` : "Draw"]} />
          <Area type="monotone" dataKey="home" stackId="1" stroke="none" fill={HOME} fillOpacity={0.9} isAnimationActive={false} />
          <Area type="monotone" dataKey="draw" stackId="1" stroke="none" fill={DRAW} fillOpacity={0.95} isAnimationActive={false} />
          <Area type="monotone" dataKey="away" stackId="1" stroke="none" fill={AWAY} fillOpacity={0.9} isAnimationActive={false} />
          <ReferenceLine x={45} stroke="#647A6C" strokeDasharray="3 4" label={{ value: "HT", fill: "#647A6C", fontSize: 10, position: "insideTop" }} />
          {reg.map((g) => g.disallowed ? (
            <ReferenceArea key={g.eventId} x1={g.minute} x2={Math.min(g.correctedAt ?? g.minute + 2, 90)}
              fill="url(#hatch)" stroke={SIGNAL} strokeDasharray="3 3"
              label={{ value: `STOOD ${g.minute}'–${g.correctedAt}'`, fill: SIGNAL, fontSize: 9.5, position: "insideTop" }} />
          ) : (
            <ReferenceLine key={g.eventId} x={g.minute} stroke="#F2F6F0" strokeOpacity={0.55} />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
