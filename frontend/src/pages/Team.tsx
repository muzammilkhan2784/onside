import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import clsx from "clsx";
import { api } from "../lib/api";
import { longDate } from "../lib/format";
import { FixtureRow } from "../components/MatchCard";
import { ErrorState, PageSkeleton, Skeleton } from "../components/States";
import { Crest } from "../components/Football";

export default function TeamPage() {
  const { tid = "" } = useParams();
  const team = useQuery({ queryKey: ["team", tid], queryFn: () => api.team(tid) });
  const form = useQuery({ queryKey: ["form", tid], queryFn: () => api.teamForm(tid) });
  const matches = useInfiniteQuery({
    queryKey: ["team-matches", tid],
    queryFn: ({ pageParam }) => api.teamMatches(tid, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (p) => p.next,
  });
  if (team.isLoading) return <PageSkeleton />;
  if (team.error || !team.data) return <ErrorState error={team.error} />;
  const t = team.data;
  const items = matches.data?.pages.flatMap((p) => p.items) ?? [];
  const stat = (label: string, value: string | number, sub?: string) => (
    <div className="rounded-2xl border border-rule bg-deck p-4">
      <dt className="eyebrow">{label}</dt><dd className="mt-1 font-display text-3xl num">{value}</dd>
      {sub && <p className="text-[11.5px] text-dim">{sub}</p>}
    </div>
  );
  return (
    <div className="space-y-6">
      <div className="turf flex items-center gap-5 rounded-3xl border border-rule p-5 sm:p-7">
        <Crest name={t.name} size={72} className="drop-shadow-lg" />
        <div className="min-w-0">
          <p className="eyebrow truncate">{t.competitions.join(" · ")}</p>
          <h1 className="mt-1 font-display text-4xl uppercase leading-none sm:text-6xl [overflow-wrap:anywhere]">{t.name}</h1>
          <p className="mt-1 text-mute">In the archive from {longDate(t.first)} to {longDate(t.last)}</p>
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {stat("Matches", t.matches)}
        {stat("Record", `${t.won}-${t.drawn}-${t.lost}`, "won · drawn · lost")}
        {stat("Win rate", `${Math.round((t.won / Math.max(1, t.matches)) * 100)}%`)}
        {stat("Goals", `${t.goalsFor}:${t.goalsAgainst}`, "scored : conceded")}
        {stat("xG", `${t.xgFor}:${t.xgAgainst}`, "created : allowed")}
      </dl>
      {form.data && form.data.form.length > 0 && (
        <section className="flex flex-wrap items-center gap-2">
          <span className="eyebrow mr-1">Last five</span>
          {form.data.form.map((f) => (
            <span key={f.matchId} title={`${f.score} v ${f.opponent}, ${f.date}`}
              className={clsx("grid h-8 w-8 place-items-center rounded-lg font-mono text-[12px] font-bold",
                f.result === "W" && "bg-grass/20 text-grass", f.result === "D" && "bg-deck2 text-mute", f.result === "L" && "bg-away/15 text-away")}>{f.result}</span>
          ))}
        </section>
      )}
      <section className="panel overflow-hidden">
        <div className="panel-head"><h2 className="h-section">Matches</h2><span className="text-[12px] text-dim">Newest first</span></div>
        {matches.isLoading ? <Skeleton className="m-4 h-64" /> : items.map((m) => <FixtureRow key={m.id} card={m} focusTeam={tid} />)}
        {matches.hasNextPage && (
          <div className="p-3"><button className="btn" onClick={() => matches.fetchNextPage()} disabled={matches.isFetchingNextPage}>
            {matches.isFetchingNextPage ? "Loading…" : "Older matches"}</button></div>
        )}
      </section>
    </div>
  );
}
