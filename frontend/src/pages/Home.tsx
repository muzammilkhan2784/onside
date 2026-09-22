import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "../lib/api";
import { compact, longDate } from "../lib/format";
import type { Collection, Home as HomeData, MatchCard, SocialTopic } from "../lib/types";
import { FixtureRow, StoryCard } from "../components/MatchCard";
import { CompetitionMark, ReplayBadge } from "../components/Football";
import { CurrentOff, FixtureList, FreshnessNote, MatchdayHero, PRIORITY, StandingsTable, usable, useToday } from "../components/Current";
import { PostCard } from "../components/Social";
import { useFeatures } from "../hooks/useFeatures";
import { ErrorState, PageSkeleton, Skeleton } from "../components/States";

// ------------------------------------------------------------------ now

function BuzzPreview({ topics }: { topics: SocialTopic[] }) {
  const q = useQuery({ queryKey: ["social-home"], queryFn: () => api.social({ limit: 4, lang: "en" }), refetchInterval: 60_000 });
  const map = useMemo(() => new Map(topics.map((t) => [t.id, t])), [topics]);
  return (
    <section className="panel overflow-hidden">
      <div className="panel-head"><h2 className="h-section">Buzz</h2><Link to="/buzz" className="text-[12px] font-bold text-mute hover:text-chalk">Open the dashboard →</Link></div>
      {q.isLoading ? <Skeleton className="m-4 h-48" />
        : q.data?.items.length ? q.data.items.map((p) => <PostCard key={p.id} post={p} topics={map} />)
        : <p className="p-4 text-[13px] text-mute">Posts about this week's matches appear here within a few minutes of the social service starting.</p>}
    </section>
  );
}

function TableWidget({ codes }: { codes: string[] }) {
  const options = PRIORITY.filter((c) => codes.includes(c) && c !== "CL" && c !== "CLI").slice(0, 5);
  const [code, setCode] = useState<string>("");
  const active = code || options[0];
  const names: Record<string, string> = { PL: "Premier League", PD: "La Liga", BL1: "Bundesliga", SA: "Serie A", FL1: "Ligue 1", ELC: "Championship", DED: "Eredivisie", PPL: "Primeira Liga", BSA: "Brasileirão" };
  if (!active) return null;
  return (
    <section className="panel overflow-hidden">
      <div className="panel-head"><h2 className="h-section">Tables</h2><Link to={`/matches?tab=tables&c=${active}`} className="text-[12px] font-bold text-mute hover:text-chalk">Full table →</Link></div>
      <div className="flex gap-1 overflow-x-auto border-b border-rule px-3 py-2 scroll-x">
        {options.map((c) => (
          <button key={c} onClick={() => setCode(c)} aria-pressed={active === c}
            className={clsx("shrink-0 rounded-full px-2.5 py-1 text-[12px] font-bold", active === c ? "bg-grass/15 text-grass" : "text-mute hover:text-chalk")}>
            {names[c] ?? c}
          </button>
        ))}
      </div>
      <StandingsTable code={active} limit={8} />
    </section>
  );
}

// ------------------------------------------------------------------ the archive

function ReplayingNow({ live }: { live: MatchCard[] }) {
  if (!live.length) return null;
  return (
    <section className="panel overflow-hidden border-replay/40">
      <div className="panel-head"><h2 className="h-section">Replaying now</h2><Link to="/replays" className="text-[12px] font-bold text-replay">Replay room →</Link></div>
      {live.map((m) => <FixtureRow key={m.id} card={m} showDate={false} />)}
      <p className="px-4 py-2 text-[11.5px] text-dim">Archived matches being re-run - not today's fixtures.</p>
    </section>
  );
}

function CollectionRail({ c }: { c: Collection }) {
  if (!c.matches.length) return null;
  return (
    <section className="space-y-3">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h3 className="h-section">{c.title}</h3>
          <p className="text-[13px] text-dim">{c.blurb}</p>
        </div>
        <Link to={`/news?collection=${c.id}`} className="shrink-0 text-[13px] font-bold text-mute hover:text-chalk">See all →</Link>
      </div>
      <div className="-mx-4 flex snap-x gap-4 overflow-x-auto px-4 pb-2 scroll-x">
        {c.matches.map((m) => <div key={m.id} className="w-[19rem] shrink-0 snap-start"><StoryCard card={m} /></div>)}
      </div>
    </section>
  );
}

function ArchiveIntro({ archive }: { archive: HomeData["archive"] }) {
  const replays = useFeatures()?.replays !== false;
  return (
    <section className="grid gap-5 rounded-3xl border border-rule bg-deck/60 p-6 lg:grid-cols-[1.4fr_1fr]">
      <div>
        <p className="eyebrow mb-2">From the archive · {archive.from.slice(0, 4)}–{archive.to.slice(0, 4)}</p>
        <h2 className="font-display text-3xl uppercase leading-none sm:text-4xl">Every match. Every event. <span className="text-grass">Every correction.</span></h2>
        <p className="mt-3 max-w-xl text-[14px] text-mute">
          {compact(archive.matches)} finished matches from StatsBomb's open data, each with its full event log, a win-probability
          model, a written report and a shot map. Nothing here is live{replays ? <> - but any of it can be{" "}
          <Link to="/replays" className="font-bold text-replay">replayed</Link>, minute by minute, with a VAR check that corrects the score in front of you</> : ""}.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Link to="/news" className="btn">Match reports →</Link>
          <Link to="/competitions" className="btn">Browse competitions →</Link>
          {replays && <Link to="/replays" className="btn btn-replay">Replay room →</Link>}
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-2 self-end">
        {[[compact(archive.matches), "matches"], [compact(archive.events), "events"], [String(archive.competitions), "competitions"],
          [`${archive.from.slice(0, 4)}–${archive.to.slice(0, 4)}`, "seasons span"]].map(([v, k]) => (
          <div key={k} className="rounded-xl border border-rule bg-deck px-3 py-2.5">
            <dt className="eyebrow">{k}</dt><dd className="font-display text-2xl num">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export default function Home() {
  const home = useQuery({ queryKey: ["home"], queryFn: api.home, refetchInterval: 60_000 });
  const today = useToday();
  const overview = useQuery({ queryKey: ["social-overview"], queryFn: api.socialOverview, refetchInterval: 60_000 });
  const comps = useQuery({ queryKey: ["current-comps"], queryFn: api.currentCompetitions, staleTime: 600_000 });
  const topics = overview.data?.topics ?? [];
  const buzz = useMemo(() => Object.fromEntries(topics.map((t) => [t.id, t.posts])), [topics]);

  if (home.isLoading && today.isLoading) return <PageSkeleton />;
  const current = usable(today.data);
  const results = (today.data?.matches ?? []).filter((m) => m.status === "finished").reverse();

  return (
    <div className="space-y-10">
      <div className="grid gap-4 lg:grid-cols-[1.7fr_1fr]">
        <div className="space-y-4">
          {today.isLoading ? <Skeleton className="h-80 rounded-3xl" />
            : current && today.data ? (
              <MatchdayHero today={today.data} topics={topics} />
            ) : <section className="panel"><CurrentOff data={today.data} error={today.error} /></section>}
          {current && results.length > 0 && (
            <section className="panel overflow-hidden">
              <div className="panel-head"><h2 className="h-section">Latest results</h2><Link to="/matches" className="text-[12px] font-bold text-mute hover:text-chalk">All matches →</Link></div>
              <FixtureList matches={results} buzz={buzz} maxPerCompetition={4} newestFirst />
              <FreshnessNote stale={today.data?.stale} />
            </section>
          )}
        </div>
        <div className="space-y-4">
          {home.data && <ReplayingNow live={home.data.live} />}
          {current && <TableWidget codes={comps.data?.map((c) => c.code) ?? []} />}
          <BuzzPreview topics={topics} />
        </div>
      </div>

      {home.error || !home.data ? <ErrorState error={home.error} retry={home.refetch} /> : (
        <div className="space-y-8">
          <ArchiveIntro archive={home.data.archive} />
          {home.data.collections.map((c) => <CollectionRail key={c.id} c={c} />)}
          <section className="space-y-3">
            <h3 className="h-section">Archive competitions</h3>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {home.data.competitions.map((c) => (
                <Link key={c.id} to={`/competitions/${c.id}`} className="panel flex items-center gap-2.5 px-3 py-2.5 text-[13.5px] transition-colors hover:border-grass/50">
                  <CompetitionMark name={c.name} size={20} />
                  <span className="min-w-0 flex-1 truncate font-semibold">{c.name}{c.gender === "female" ? <span className="text-dim"> · W</span> : null}</span>
                  <span className="font-mono text-[11px] text-dim num">{c.matches}</span>
                </Link>
              ))}
            </div>
          </section>
          <p className="flex flex-wrap items-center gap-2 text-[12px] text-dim">
            <ReplayBadge status="idle" /> Archive: StatsBomb open data, {longDate(home.data.archive.from)} to {longDate(home.data.archive.to)}. Current matches: football-data.org. Posts: Bluesky and Mastodon.
          </p>
        </div>
      )}
    </div>
  );
}
