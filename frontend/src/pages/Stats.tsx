import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { ErrorState, Skeleton } from "../components/States";

export default function Stats() {
  const [metric, setMetric] = useState("goals");
  const [competition, setCompetition] = useState("");
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, staleTime: Infinity });
  const comps = useQuery({ queryKey: ["competitions"], queryFn: api.competitions, staleTime: 600_000 });
  const board = useQuery({
    queryKey: ["lb", metric, competition || null, null],
    queryFn: () => api.leaderboard({ metric, competition: competition || undefined }),
  });
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-4xl uppercase sm:text-5xl">Leaderboards</h1>
        <p className="max-w-2xl text-mute">
          Computed on request by DuckDB, straight from the Parquet archive - roughly fourteen million events, no pre-built aggregates.
        </p>
      </div>
      <div className="flex flex-wrap gap-3">
        <select id="metric" value={metric} onChange={(e) => setMetric(e.target.value)} className="rounded-full border border-rule bg-deck2 px-4 py-2 text-[13px]">
          {(metrics.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.id.replace(/_/g, " ")}</option>)}
        </select>
        <select id="competition" value={competition} onChange={(e) => setCompetition(e.target.value)} className="rounded-full border border-rule bg-deck2 px-4 py-2 text-[13px]">
          <option value="">Every competition</option>
          {(comps.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>
      <section className="panel overflow-hidden">
        <div className="panel-head">
          <h2 className="h-section">{board.data?.description ?? "…"}</h2>
          {board.data && <span className="font-mono text-[11px] text-dim">{board.data.queryMs} ms</span>}
        </div>
        {board.isLoading ? <Skeleton className="m-4 h-96" /> : board.error ? <ErrorState error={board.error} /> : (
          <ol className="divide-y divide-rule/50">
            {board.data!.rows.map((r, i) => (
              <li key={r.playerId} className="grid grid-cols-[2rem_1fr_auto_4rem] items-center gap-3 px-4 py-2.5 text-[13.5px]">
                <span className="font-mono text-dim num">{i + 1}</span>
                <span className="min-w-0 truncate"><Link to={`/player/${r.playerId}`} className="font-bold hover:text-grass">{r.player}</Link> <span className="text-[12px] text-dim">{r.team}</span></span>
                <span className="font-mono text-[11px] text-dim num">{r.matches} apps</span>
                <span className="text-right font-display text-[18px] num">{r.value}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
      <p className="text-[12px] text-dim">The archive is StatsBomb's open data, not every league: Barcelona's La Liga seasons are covered in depth, so Barcelona players lead most all-time boards.</p>
    </div>
  );
}
