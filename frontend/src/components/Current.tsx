import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api, ApiError } from "../lib/api";
import type { CurrentTeam, Fixture, SocialTopic, Today } from "../lib/types";
import { CompetitionMark, Crest, LiveBadge } from "./Football";
import { Skeleton } from "./States";

/**
 * Current football from football-data.org: real fixtures, results, tables and
 * scorers. Green "LIVE" appears only here, and only for a match in play.
 */

export const PLAYING = new Set(["live", "half_time"]);
/** Broadcast order when there is more football than room. */
export const PRIORITY = ["CL", "PL", "PD", "BL1", "SA", "FL1", "ELC", "DED", "PPL", "CLI", "BSA", "WC", "EC"];
const prio = (code: string) => { const i = PRIORITY.indexOf(code); return i < 0 ? 99 : i; };

export function localDay(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function dayLabel(day: string, now = new Date()): string {
  const shift = (n: number) => localDay(new Date(now.getTime() + n * 86_400_000).toISOString());
  if (day === shift(0)) return "Today";
  if (day === shift(-1)) return "Yesterday";
  if (day === shift(1)) return "Tomorrow";
  return new Date(`${day}T12:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}

export function kickoffTime(iso: string): string {
  // "19:00" or "7:00 PM", as the reader's locale writes it - without a
  // leading zero, which on a phone is the difference between one line and two.
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export function useToday() {
  return useQuery({ queryKey: ["today"], queryFn: api.today, refetchInterval: 60_000 });
}

export const usable = (t?: Today) => !!t?.enabled && t.ok !== false;

/** The one match to put first: live, else the next kick-off, else the latest
 *  result - bigger competitions first within each. */
export function headline(matches: Fixture[], now = Date.now()): { fixture: Fixture; why: "live" | "next" | "result" } | null {
  const byPrio = (a: Fixture, b: Fixture) => prio(a.competition.code) - prio(b.competition.code);
  const live = matches.filter((m) => PLAYING.has(m.status)).sort(byPrio);
  if (live.length) return { fixture: live[0], why: "live" };
  const soon = matches.filter((m) => m.status === "scheduled" && Date.parse(m.kickoffUtc) > now)
    .sort((a, b) => Date.parse(a.kickoffUtc) - Date.parse(b.kickoffUtc));
  if (soon.length) {
    // Among matches in the next two days of football, the bigger competition
    // leads - a Premier League Saturday over a Friday night elsewhere.
    const first = Date.parse(soon[0].kickoffUtc);
    const pool = soon.filter((m) => Date.parse(m.kickoffUtc) - first < 48 * 3600_000)
      .sort((a, b) => byPrio(a, b) || Date.parse(a.kickoffUtc) - Date.parse(b.kickoffUtc));
    return { fixture: pool[0], why: "next" };
  }
  const done = matches.filter((m) => m.status === "finished")
    .sort((a, b) => Date.parse(b.kickoffUtc) - Date.parse(a.kickoffUtc));
  if (!done.length) return null;
  // Among the last day and a half of results, the biggest competition leads.
  const newest = Date.parse(done[0].kickoffUtc);
  const recent = done.filter((m) => newest - Date.parse(m.kickoffUtc) < 36 * 3600_000).sort(byPrio);
  return { fixture: recent[0], why: "result" };
}

function StatusCell({ f }: { f: Fixture }) {
  if (PLAYING.has(f.status)) return <span className="text-live">{f.status === "half_time" ? "HT" : "LIVE"}</span>;
  if (f.status === "finished") return <span className="text-mute">FT</span>;
  if (f.status === "postponed") return <span className="text-away">PP</span>;
  if (f.status === "cancelled") return <span className="text-away">CAN</span>;
  if (f.status === "suspended") return <span className="text-away">SUS</span>;
  return <span className="text-chalk">{kickoffTime(f.kickoffUtc)}</span>;
}

export function FixtureLine({ f, buzz }: { f: Fixture; buzz?: number }) {
  const [h, a] = f.score;
  const played = f.status === "finished" || PLAYING.has(f.status);
  const homeWon = played && h !== null && a !== null && h > a;
  const awayWon = played && h !== null && a !== null && a > h;
  const body = (
    <>
      <span className="font-mono text-[10.5px] font-bold leading-tight num sm:text-[11px]"><StatusCell f={f} /></span>
      <span className="flex min-w-0 items-center justify-end gap-2">
        <span className={clsx("truncate text-right", homeWon ? "font-extrabold" : played ? "text-mute" : "font-semibold")}>{f.home.name}</span>
        <Crest name={f.home.name} code={f.home.code} size={18} />
      </span>
      <span className={clsx("min-w-[3.2rem] rounded-md px-2 py-1 text-center font-display text-[15px] leading-none ring-1 num",
        PLAYING.has(f.status) ? "bg-live/10 text-live ring-live/40" : "bg-night/70 ring-rule")}>
        {played && h !== null ? `${h}–${a}` : <span className="font-sans text-[11px] font-bold text-dim">vs</span>}
      </span>
      <span className="flex min-w-0 items-center gap-2">
        <Crest name={f.away.name} code={f.away.code} size={18} />
        <span className={clsx("truncate", awayWon ? "font-extrabold" : played ? "text-mute" : "font-semibold")}>{f.away.name}</span>
      </span>
      <span className="justify-self-end font-mono text-[10.5px] text-dim num">
        {buzz ? <span className="whitespace-nowrap rounded-full border border-rule px-1.5 py-0.5 text-mute" title={`${buzz} posts about this match in the last day`}>💬 {buzz}</span> : null}
      </span>
    </>
  );
  // Minmax(0, 1fr) lets the team names use every spare pixel before they
  // truncate; the post-count column takes no room when there is no count.
  const cls = "grid grid-cols-[3rem_minmax(0,1fr)_auto_minmax(0,1fr)_auto] items-center gap-1.5 border-b border-rule/60 px-2.5 py-2.5 text-[13px] last:border-0 sm:grid-cols-[4.2rem_minmax(0,1fr)_auto_minmax(0,1fr)_3.4rem] sm:gap-3 sm:px-4 sm:text-[13.5px]";
  return buzz !== undefined
    ? <Link to={`/buzz?topic=${f.id}`} className={clsx(cls, "transition-colors hover:bg-deck2/60")} aria-label={`${f.home.name} v ${f.away.name} - see what people are saying`}>{body}</Link>
    : <div className={cls}>{body}</div>;
}

export function groupFixtures(matches: Fixture[], newestFirst = false): [string, [string, Fixture[]][]][] {
  const days = new Map<string, Map<string, Fixture[]>>();
  for (const f of matches) {
    const day = localDay(f.kickoffUtc);
    const comps = days.get(day) ?? days.set(day, new Map()).get(day)!;
    (comps.get(f.competition.code) ?? comps.set(f.competition.code, []).get(f.competition.code)!).push(f);
  }
  return [...days.entries()].sort(([a], [b]) => (newestFirst ? b.localeCompare(a) : a.localeCompare(b)))
    .map(([d, comps]) => [d, [...comps.entries()].sort(([a], [b]) => prio(a) - prio(b))]);
}

export function FixtureList({ matches, buzz = {}, maxPerCompetition, newestFirst = false }:
  { matches: Fixture[]; buzz?: Record<string, number>; maxPerCompetition?: number; newestFirst?: boolean }) {
  const days = useMemo(() => groupFixtures(matches, newestFirst), [matches, newestFirst]);
  if (!matches.length) return <p className="p-4 text-[13.5px] text-mute">No matches here in this window.</p>;
  return (
    <>
      {days.map(([day, comps]) => (
        <div key={day}>
          <p className="border-b border-rule bg-deck2/60 px-4 py-1.5 font-mono text-[11px] font-bold uppercase tracking-wider text-mute">{dayLabel(day)}</p>
          {comps.map(([code, list]) => (
            <div key={code}>
              <p className="flex items-center gap-2 px-4 pb-1 pt-2.5 text-[12px] font-bold text-mute">
                <CompetitionMark name={list[0].competition.name} size={16} />{list[0].competition.name}
                {list[0].matchday ? <span className="font-normal text-dim">· Matchday {list[0].matchday}</span> : null}
              </p>
              {(maxPerCompetition ? list.slice(0, maxPerCompetition) : list).map((f) => <FixtureLine key={f.id} f={f} buzz={buzz[f.id]} />)}
            </div>
          ))}
        </div>
      ))}
    </>
  );
}

export function CurrentOff({ data, error }: { data?: Today; error?: unknown }) {
  const message = error ? (error instanceof ApiError ? error.message : "The fixtures service did not answer. Try again in a minute.") : data?.message;
  return (
    <div className="p-5 text-[13.5px] text-mute">
      <p className="font-bold text-chalk">{data?.enabled === false ? "Current fixtures are switched off here." : "Current fixtures could not be loaded."}</p>
      <p className="mt-1 max-w-2xl">{message}</p>
      <p className="mt-2 max-w-2xl text-[12.5px] text-dim">
        The <Link to="/news" className="link">archive</Link> still works: every match there is finished, with its full-time result, and{" "}
        <Link to="/replays" className="font-bold text-replay">replays</Link> are labelled as replays.
      </p>
    </div>
  );
}

export function FreshnessNote({ stale }: { stale?: boolean }) {
  return (
    <p className="border-t border-rule px-4 py-2 text-[11.5px] text-dim">
      Real fixtures from football-data.org{stale ? " - the last update was more than five minutes ago" : ""}. Free-tier scores can run a few minutes behind. Times are in your time zone.
    </p>
  );
}

function TeamCell({ team, size = 18 }: { team: CurrentTeam; size?: number }) {
  return <span className="flex min-w-0 items-center gap-2"><Crest name={team.name} code={team.code} size={size} /><span className="truncate font-bold">{team.name}</span></span>;
}

export function StandingsTable({ code, limit }: { code: string; limit?: number }) {
  const q = useQuery({ queryKey: ["current-standings", code], queryFn: () => api.currentStandings(code), staleTime: 120_000, retry: false });
  if (q.isLoading) return <Skeleton className="m-4 h-56" />;
  if (q.error || !q.data) return <p className="p-4 text-[13px] text-mute">{q.error instanceof ApiError ? q.error.message : "No table yet."}</p>;
  return (
    <div>
      {q.data.tables.map((t) => (
        <div key={`${t.stage}-${t.group}`} className="scroll-x">
          {q.data.tables.length > 1 && <p className="eyebrow px-4 pt-3">{t.group || t.stage}</p>}
          <table className="w-full text-[13px] num">
            <thead className="text-left font-mono text-[10.5px] uppercase tracking-wider text-dim">
              <tr>
                <th className="px-3 py-2 font-normal">#</th><th className="px-2 py-2 font-normal">Team</th>
                <th className="px-2 py-2 text-right font-normal">P</th>
                {!limit && <><th className="px-2 py-2 text-right font-normal">W</th><th className="px-2 py-2 text-right font-normal">D</th><th className="px-2 py-2 text-right font-normal">L</th></>}
                <th className="px-2 py-2 text-right font-normal">GD</th><th className="px-3 py-2 text-right font-normal">Pts</th>
              </tr>
            </thead>
            <tbody>
              {(limit ? t.rows.slice(0, limit) : t.rows).map((r) => (
                <tr key={r.team.id} className="border-t border-rule/60">
                  <td className="px-3 py-1.5 font-mono text-dim">{r.position}</td>
                  <td className="max-w-[12rem] px-2 py-1.5"><TeamCell team={r.team} /></td>
                  <td className="px-2 py-1.5 text-right text-mute">{r.played}</td>
                  {!limit && <><td className="px-2 py-1.5 text-right text-mute">{r.won}</td><td className="px-2 py-1.5 text-right text-mute">{r.drawn}</td><td className="px-2 py-1.5 text-right text-mute">{r.lost}</td></>}
                  <td className="px-2 py-1.5 text-right">{r.goalDifference > 0 ? `+${r.goalDifference}` : r.goalDifference}</td>
                  <td className="px-3 py-1.5 text-right font-display text-[15px]">{r.points}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      <p className="px-4 py-2 text-[11px] text-dim">{q.data.matchday ? `After matchday ${q.data.matchday}. ` : ""}From football-data.org{q.data.stale ? ", not refreshed in the last few minutes" : ""}.</p>
    </div>
  );
}

export function ScorersList({ code, limit = 20 }: { code: string; limit?: number }) {
  const q = useQuery({ queryKey: ["current-scorers", code], queryFn: () => api.currentScorers(code), staleTime: 300_000, retry: false });
  if (q.isLoading) return <Skeleton className="m-4 h-56" />;
  if (q.error || !q.data) return <p className="p-4 text-[13px] text-mute">{q.error instanceof ApiError ? q.error.message : "No scorers yet."}</p>;
  return (
    <ol className="divide-y divide-rule/60">
      {q.data.rows.slice(0, limit).map((s, i) => (
        <li key={`${s.player}-${s.team.id}`} className="flex items-center gap-3 px-4 py-2 text-[13px]">
          <span className="w-5 font-mono text-dim num">{i + 1}</span>
          <Crest name={s.team.name} code={s.team.code} size={18} />
          <span className="min-w-0 flex-1">
            <span className="block truncate font-bold">{s.player}</span>
            <span className="block truncate text-[11.5px] text-dim">{s.team.name}{s.penalties ? ` · ${s.penalties} pen` : ""}{s.assists ? ` · ${s.assists} assists` : ""}</span>
          </span>
          <span className="font-display text-[18px] num">{s.goals}</span>
        </li>
      ))}
    </ol>
  );
}

/** Home page lead: the one match that matters most right now. */
export function MatchdayHero({ today, topics }: { today: Today; topics: SocialTopic[] }) {
  const pick = headline(today.matches);
  if (!pick) return null;
  const f = pick.fixture;
  const [h, a] = f.score;
  const played = f.status === "finished" || PLAYING.has(f.status);
  const buzz = topics.find((t) => t.id === f.id)?.posts;
  const others = today.matches
    .filter((m) => m.id !== f.id && (PLAYING.has(m.status) || (m.status === "scheduled" && localDay(m.kickoffUtc) === localDay(f.kickoffUtc))))
    .sort((x, y) => prio(x.competition.code) - prio(y.competition.code)).slice(0, 4);
  return (
    <section className="turf relative overflow-hidden rounded-3xl border border-rule">
      <div className="absolute inset-x-0 top-0 h-[3px] bg-gradient-to-r from-home via-grass to-away" aria-hidden />
      <div className="flex flex-wrap items-center gap-2 px-5 pt-5 sm:px-8">
        {pick.why === "live" ? <LiveBadge label="Live now" /> : (
          <span className="font-mono text-[10.5px] font-bold uppercase tracking-[0.12em] text-grass">{pick.why === "next" ? "Next up" : "Latest result"}</span>
        )}
        <span className="chip gap-2 bg-night/40"><CompetitionMark name={f.competition.name} size={16} />{f.competition.name}{f.matchday ? ` · Matchday ${f.matchday}` : ""}</span>
        <span className="chip bg-night/40">{dayLabel(localDay(f.kickoffUtc))} · {kickoffTime(f.kickoffUtc)}</span>
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 px-5 py-7 sm:px-8">
        <span className="flex min-w-0 flex-col items-center gap-2 text-center sm:flex-row sm:text-left">
          <Crest name={f.home.name} code={f.home.code} size={52} />
          <span className="font-display text-xl uppercase leading-none sm:text-4xl [overflow-wrap:anywhere]">{f.home.name}</span>
        </span>
        <span className="text-center">
          <span className={clsx("block rounded-2xl px-4 py-2 font-display text-5xl leading-none ring-1 num sm:text-7xl",
            PLAYING.has(f.status) ? "bg-night/80 text-live ring-live/40" : "bg-night/80 ring-white/10")}>
            {played && h !== null ? <>{h}<span className="mx-2 text-dim">-</span>{a}</> : <span className="text-3xl sm:text-5xl">{kickoffTime(f.kickoffUtc)}</span>}
          </span>
          <span className="mt-2 block font-mono text-[11px] font-bold uppercase tracking-wider text-mute">
            {f.status === "finished" ? "Full time" : f.status === "half_time" ? "Half time" : f.status === "live" ? "In play" : "Kick-off, your time"}
          </span>
        </span>
        <span className="flex min-w-0 flex-col-reverse items-center gap-2 text-center sm:flex-row sm:justify-end sm:text-right">
          <span className="font-display text-xl uppercase leading-none sm:text-4xl [overflow-wrap:anywhere]">{f.away.name}</span>
          <Crest name={f.away.name} code={f.away.code} size={52} />
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-white/5 bg-night/30 px-5 py-4 sm:px-8">
        <Link to="/matches" className="btn btn-primary">All fixtures and results →</Link>
        <Link to={buzz !== undefined ? `/buzz?topic=${f.id}` : "/buzz"} className="btn">💬 {buzz ? `${buzz} posts about this match` : "What people are saying"}</Link>
      </div>
      {others.length > 0 && (
        <div className="border-t border-white/5 bg-night/20">
          {others.map((m) => <FixtureLine key={m.id} f={m} buzz={topics.find((t) => t.id === m.id)?.posts} />)}
        </div>
      )}
    </section>
  );
}
