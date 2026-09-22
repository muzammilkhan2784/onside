import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { longDate, pct } from "../lib/format";
import { Pitch } from "../components/Pitch";
import { ErrorState, PageSkeleton, Skeleton } from "../components/States";

export default function PlayerPage() {
  const { pid = "" } = useParams();
  const seasons = useQuery({ queryKey: ["player-seasons", pid], queryFn: () => api.playerSeasons(pid) });
  const shots = useQuery({ queryKey: ["player-shots", pid], queryFn: () => api.playerShots(pid) });
  if (seasons.isLoading) return <PageSkeleton />;
  if (seasons.error || !seasons.data) return <ErrorState error={seasons.error} />;
  const { player: p, seasons: rows, queryMs } = seasons.data;
  const goalsVsXg = p.goals - p.xg;

  return (
    <div className="space-y-6">
      <div>
        <p className="eyebrow">{p.position || "Player"} · {p.teams.slice(0, 4).join(" · ")}</p>
        <h1 className="mt-1 font-display text-4xl uppercase sm:text-6xl">{p.name}</h1>
        <p className="text-mute">In the archive from {longDate(p.first)} to {longDate(p.last)}</p>
      </div>
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {([["Matches", p.matches], ["Goals", p.goals], ["xG", p.xg.toFixed(1)], ["Assists", p.assists],
          [goalsVsXg >= 0 ? "Above xG" : "Below xG", `${goalsVsXg >= 0 ? "+" : ""}${goalsVsXg.toFixed(1)}`]] as const).map(([k, v]) => (
          <div key={k} className="rounded-2xl border border-rule bg-deck p-4"><dt className="eyebrow">{k}</dt><dd className="mt-1 font-display text-3xl num">{v}</dd></div>
        ))}
      </dl>
      <p className="text-[12.5px] text-dim">
        Goals minus expected goals: positive means finishing better than an average player would from the same chances.
        Numbers cover only matches in the open-data archive, not a full career.
      </p>

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <section className="panel overflow-hidden">
          <div className="panel-head"><h2 className="h-section">By season</h2><span className="text-[11px] text-dim">DuckDB · {queryMs} ms</span></div>
          <div className="scroll-x">
            <table className="w-full min-w-[36rem] text-[13px] num">
              <thead className="text-left font-mono text-[10.5px] uppercase tracking-wider text-dim">
                <tr>{["Season", "Team", "Apps", "Goals", "xG", "Shots", "Ast", "Pass %"].map((h, i) => <th key={h} className={`px-3 py-2 font-normal ${i > 1 ? "text-right" : ""}`}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.competitionId}-${r.seasonId}`} className="border-t border-rule/60">
                    <td className="px-3 py-2"><Link className="hover:text-grass" to={`/competitions/${r.competitionId}/${r.seasonId}`}>{r.competition} <span className="text-dim">{r.season}</span></Link></td>
                    <td className="px-3 py-2 text-mute">{r.team}</td>
                    <td className="px-3 py-2 text-right">{r.matches}</td>
                    <td className="px-3 py-2 text-right font-bold">{r.goals}</td>
                    <td className="px-3 py-2 text-right text-mute">{r.xg.toFixed(1)}</td>
                    <td className="px-3 py-2 text-right text-mute">{r.shots}</td>
                    <td className="px-3 py-2 text-right text-mute">{r.assists}</td>
                    <td className="px-3 py-2 text-right text-mute">{pct(r.passAccuracy)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section className="panel p-4">
          <h2 className="h-section mb-3">Every shot</h2>
          {shots.isLoading ? <Skeleton className="h-56" /> : shots.data && shots.data.length ? (
            <>
              <Pitch half>
                {shots.data.map((s, i) => (
                  <circle key={i} cx={s.x} cy={s.y} r={0.6 + Math.sqrt(Math.max(s.xg, 0.01)) * 2.4}
                    fill={s.outcome === "Goal" ? "#2FCB74" : "transparent"} fillOpacity={0.7}
                    stroke={s.outcome === "Goal" ? "#2FCB74" : "#5CC8FF"} strokeOpacity={s.outcome === "Goal" ? 1 : 0.45} strokeWidth={0.3}>
                    <title>{`${s.date} ${s.minute}' - xG ${s.xg} - ${s.outcome}`}</title>
                  </circle>
                ))}
              </Pitch>
              <p className="mt-2 text-[12px] text-dim">{shots.data.length} shots; amber went in. Size is expected goals.</p>
            </>
          ) : <p className="text-[13px] text-mute">No shots recorded for this player in the archive.</p>}
        </section>
      </div>
    </div>
  );
}
