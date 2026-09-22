import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "../lib/api";
import { CurrentOff, FixtureList, FreshnessNote, PLAYING, ScorersList, StandingsTable, usable, useToday } from "../components/Current";
import { CompetitionMark, LiveBadge, ReplayBadge } from "../components/Football";
import { Skeleton } from "../components/States";

const TABS = [["fixtures", "Fixtures & results"], ["tables", "Tables"], ["scorers", "Top scorers"]] as const;

/** Current football: this week's real fixtures and results, today's tables
 *  and scorers. Everything else on Onside is the archive. */
export default function Matches() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as (typeof TABS)[number][0]) || "fixtures";
  const comp = params.get("c") || "";
  const set = (k: string, v: string) => { const n = new URLSearchParams(params); if (v) n.set(k, v); else n.delete(k); setParams(n, { replace: true }); };

  const today = useToday();
  const comps = useQuery({ queryKey: ["current-comps"], queryFn: api.currentCompetitions, staleTime: 600_000 });
  const overview = useQuery({ queryKey: ["social-overview"], queryFn: api.socialOverview, refetchInterval: 60_000 });
  const buzz = useMemo(() => Object.fromEntries((overview.data?.topics ?? []).map((t) => [t.id, t.posts])), [overview.data]);

  const all = today.data?.matches ?? [];
  const live = all.filter((m) => PLAYING.has(m.status));
  const shown = comp ? all.filter((m) => m.competition.code === comp) : all;
  const upcoming = shown.filter((m) => m.status !== "finished");
  const results = shown.filter((m) => m.status === "finished").reverse();
  const codes = comps.data?.map((c) => c.code) ?? [];
  const tableCode = comp || (codes.includes("PL") ? "PL" : codes[0]) || "";

  return (
    <div className="space-y-5">
      <div>
        <h1 className="font-display text-4xl uppercase sm:text-5xl">Matches</h1>
        <p className="mt-1 max-w-2xl text-mute">
          Real fixtures, results, tables and scorers from football-data.org: the last three days and the next two weeks. A <LiveBadge />{" "}
          badge means a match is being played right now. Archived matches say full time, and replays of them are marked{" "}
          <ReplayBadge status="idle" />.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-1" role="tablist">
        {TABS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => set("tab", id === "fixtures" ? "" : id)}
            className={clsx("rounded-full px-4 py-2 text-[13px] font-bold", tab === id ? "bg-grass text-[#03170A]" : "text-mute hover:text-chalk")}>{label}</button>
        ))}
        {live.length > 0 && <span className="ml-2"><LiveBadge label={`${live.length} live now`} /></span>}
      </div>

      <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 scroll-x">
        {tab === "fixtures" && (
          <button onClick={() => set("c", "")} aria-pressed={!comp} className={clsx("chip shrink-0", !comp && "border-grass/60 text-chalk")}>All competitions</button>
        )}
        {(comps.data ?? []).map((c) => (
          <button key={c.code} onClick={() => set("c", c.code)} aria-pressed={(tab === "fixtures" ? comp : tableCode) === c.code}
            className={clsx("chip shrink-0 gap-2", (tab === "fixtures" ? comp : tableCode) === c.code && "border-grass/60 text-chalk")}>
            <CompetitionMark name={c.name} size={14} />{c.name}
          </button>
        ))}
      </div>

      {today.isLoading ? <Skeleton className="h-96" /> : !usable(today.data) || today.error ? (
        <section className="panel"><CurrentOff data={today.data} error={today.error} /></section>
      ) : tab === "fixtures" ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="panel overflow-hidden">
            <div className="panel-head"><h2 className="h-section">Live and upcoming</h2><span className="text-[12px] text-dim">{upcoming.length} matches</span></div>
            <FixtureList matches={upcoming} buzz={buzz} />
            <FreshnessNote stale={today.data?.stale} />
          </section>
          <section className="panel overflow-hidden">
            <div className="panel-head"><h2 className="h-section">Results</h2><span className="text-[12px] text-dim">last three days</span></div>
            <FixtureList matches={results} buzz={buzz} newestFirst />
          </section>
        </div>
      ) : (
        <section className="panel overflow-hidden">
          <div className="panel-head">
            <h2 className="h-section">{comps.data?.find((c) => c.code === tableCode)?.name ?? "Competition"} · {tab === "tables" ? "Table" : "Top scorers"}</h2>
          </div>
          {!tableCode ? <p className="p-4 text-[13px] text-mute">Competitions appear a minute after the fixtures service starts.</p>
            : tab === "tables" ? <StandingsTable code={tableCode} /> : <ScorersList code={tableCode} />}
        </section>
      )}
    </div>
  );
}
