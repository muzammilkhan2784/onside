import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "../lib/api";
import type { MatchCard } from "../lib/types";
import { FixtureRow } from "../components/MatchCard";
import { LeagueTable } from "../components/MatchParts";
import { Empty, ErrorState, PageSkeleton, Skeleton } from "../components/States";
import { CompetitionMark } from "../components/Football";

function groupFixtures(cards: MatchCard[]): [string, MatchCard[]][] {
  const out = new Map<string, MatchCard[]>();
  for (const c of cards) {
    const key = c.stage === "Regular Season" ? (c.matchWeek ? `Matchweek ${c.matchWeek}` : "Regular season") : c.stage || "Matches";
    (out.get(key) ?? out.set(key, []).get(key)!).push(c);
  }
  return [...out.entries()];
}

function Leaders({ cid, sid }: { cid: string; sid: string }) {
  const [metric, setMetric] = useState("goals");
  const q = useQuery({ queryKey: ["lb", metric, cid, sid], queryFn: () => api.leaderboard({ metric, competition: cid, season: sid }) });
  return (
    <section className="panel overflow-hidden">
      <div className="panel-head">
        <h2 className="h-section">Leaders</h2>
        <select id="leader-metric" value={metric} onChange={(e) => setMetric(e.target.value)}
          className="rounded-full border border-rule bg-deck2 px-3 py-1 text-[12.5px]">
          {["goals", "xg", "assists", "key_passes", "progressive_passes", "dribbles"].map((m) => <option key={m} value={m}>{m.replace("_", " ")}</option>)}
        </select>
      </div>
      {q.isLoading ? <Skeleton className="m-4 h-56" /> : q.data ? (
        <ol className="divide-y divide-rule/50">
          {q.data.rows.slice(0, 10).map((r, i) => (
            <li key={r.playerId} className="flex items-center gap-3 px-4 py-2 text-[13px]">
              <span className="w-5 font-mono text-dim num">{i + 1}</span>
              <Link to={`/player/${r.playerId}`} className="truncate font-bold hover:text-grass">{r.player}</Link>
              <span className="truncate text-[12px] text-dim">{r.team}</span>
              <span className="ml-auto font-display text-[16px] num">{r.value}</span>
            </li>
          ))}
          <li className="px-4 py-2 text-[11px] text-dim">{q.data.description}. DuckDB over the Parquet archive in {q.data.queryMs} ms.</li>
        </ol>
      ) : <ErrorState error={q.error} />}
    </section>
  );
}

export default function CompetitionPage() {
  const { cid = "", sid } = useParams();
  const nav = useNavigate();
  const comp = useQuery({ queryKey: ["competition", cid], queryFn: () => api.competition(cid) });
  const season = sid ?? comp.data?.seasons[0]?.id;
  const matches = useQuery({ queryKey: ["season", cid, season], queryFn: () => api.seasonMatches(cid, season!), enabled: !!season });
  const tables = useQuery({ queryKey: ["tables", cid, season], queryFn: () => api.tables(cid, season!), enabled: !!season });
  const [view, setView] = useState<"fixtures" | "table">("fixtures");
  const grouped = useMemo(() => groupFixtures(matches.data ?? []), [matches.data]);

  if (comp.isLoading) return <PageSkeleton />;
  if (comp.error || !comp.data) return <ErrorState error={comp.error} />;
  const c = comp.data;
  const s = c.seasons.find((x) => x.id === season);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link to="/competitions" className="text-[13px] text-mute hover:text-chalk">← Competitions</Link>
          <h1 className="mt-2 flex items-center gap-3 font-display text-4xl uppercase sm:text-5xl"><CompetitionMark name={c.name} size={44} />{c.name}</h1>
          <p className="text-mute">{c.country}{c.gender === "female" ? " · Women" : ""} · {c.matches.toLocaleString()} matches in the archive</p>
        </div>
        <label className="flex items-center gap-2 text-[13px] text-mute">
          Season
          <select id="season-select" value={season} onChange={(e) => nav(`/competitions/${cid}/${e.target.value}`)}
            className="rounded-full border border-rule bg-deck2 px-3 py-1.5 text-chalk">
            {c.seasons.map((x) => <option key={x.id} value={x.id}>{x.name} ({x.matches})</option>)}
          </select>
        </label>
      </div>

      <div className="flex gap-1" role="tablist">
        {(["fixtures", "table"] as const).map((v) => (
          <button key={v} role="tab" aria-selected={view === v} onClick={() => setView(v)}
            className={clsx("rounded-full px-4 py-2 text-[13px] font-bold capitalize", view === v ? "bg-grass text-[#03170A]" : "text-mute hover:text-chalk")}>{v === "table" ? "Tables" : "Results"}</button>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <div className="space-y-4">
          {view === "fixtures" && (matches.isLoading ? <Skeleton className="h-96" /> : matches.error ? <ErrorState error={matches.error} /> : (
            grouped.length === 0 ? <Empty title="No matches for this season." /> : grouped.map(([label, cards]) => (
              <section key={label} className="panel overflow-hidden">
                <div className="panel-head"><h2 className="h-section">{label}</h2><span className="font-mono text-[11px] text-dim">{cards.length}</span></div>
                {cards.map((m) => <FixtureRow key={m.id} card={m} />)}
              </section>
            ))
          ))}
          {view === "table" && (tables.isLoading ? <Skeleton className="h-96" /> : tables.data && (
            <>
              {tables.data.note && <p className="rounded-2xl border border-rule bg-deck px-4 py-3 text-[13px] text-mute">{tables.data.note}</p>}
              {tables.data.tables.map((t) => <LeagueTable key={t.group} table={t} />)}
              {!tables.data.tables.length && !tables.data.note && <Empty title="No table for this season." />}
            </>
          ))}
        </div>
        <aside className="space-y-4">
          {season && <Leaders cid={cid} sid={season} />}
          {s && <p className="text-[12px] text-dim">{s.name}: {s.matches} matches from {s.from} to {s.to}.</p>}
        </aside>
      </div>
    </div>
  );
}
