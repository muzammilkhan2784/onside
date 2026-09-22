import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "../lib/api";
import { longDate } from "../lib/format";
import type { MatchState } from "../lib/types";
import { useLiveMatch, type Connection } from "../hooks/useLiveMatch";
import WinProbabilityChart from "../components/WinProbabilityChart";
import { PassNetworkView, ShotMap } from "../components/Pitch";
import { ReportView, StatBars, Timeline } from "../components/MatchParts";
import { ErrorState, PageSkeleton, Skeleton } from "../components/States";
import { ApiError } from "../lib/api";
import { Ball, Card, CompetitionMark, Crest, FormationPitch, ReplayBadge } from "../components/Football";

const TABS = ["summary", "timeline", "stats", "shots", "passing", "report", "lineups"] as const;
type Tab = (typeof TABS)[number];

function ConnectionBadge({ c }: { c: Connection }) {
  if (c === "closed") return null;
  const text = { connecting: "Connecting to the replay", live: "Replay feed connected", reconnecting: "Reconnecting — showing the last score received" }[c];
  return (
    <span className={clsx("chip", c === "live" ? "border-replay/40 text-replay" : "border-signal/40 text-signal")} role="status">
      {c === "live" && <i className="h-1.5 w-1.5 animate-blip rounded-full bg-replay" />}{text}
    </span>
  );
}

function clockLabel(s: MatchState): string {
  const ft = s.shootout ? "Full time · penalties" : "Full time";
  if (!s.live || s.status === "finished") return ft;
  if (s.replay?.status === "stopped") return `Replay stopped · ${s.clock?.minute ?? 0}'`;
  if (s.status === "half_time") return "Half time";
  if (s.clock?.period === 5) return "Penalties";
  return `${s.clock?.minute ?? 0}'`;
}

function cardColour(card: string): "yellow" | "red" | "second" {
  return /second/i.test(card) ? "second" : /red/i.test(card) ? "red" : "yellow";
}

function Scorers({ s, home }: { s: MatchState; home: boolean }) {
  const goals = s.goals.filter((g) => g.home === home && g.period < 5);
  const reds = s.cards.filter((c) => c.home === home && cardColour(c.card) !== "yellow");
  return (
    <ul className={clsx("space-y-0.5 text-[12.5px] text-mute", !home && "text-right")}>
      {goals.map((g) => (
        <li key={g.eventId} className={clsx("flex items-center gap-1.5", !home && "flex-row-reverse", g.disallowed && "text-signal")}>
          <Ball className={g.disallowed ? "opacity-40" : ""} />
          <span className={clsx(g.disallowed && "line-through decoration-signal")}>
            {g.player} {g.minute}'{g.type === "Penalty" ? " (pen)" : ""}{g.ownGoal ? " (og)" : ""}
          </span>
          {g.disallowed && <span className="font-mono text-[10px] uppercase">VAR</span>}
        </li>
      ))}
      {reds.map((c) => (
        <li key={c.eventId} className={clsx("flex items-center gap-1.5", !home && "flex-row-reverse")}>
          <Card colour={cardColour(c.card)} /><span>{c.player} {c.minute}'</span>
        </li>
      ))}
    </ul>
  );
}

function Scoreboard({ s, connection }: { s: MatchState; connection: Connection }) {
  const [bump, setBump] = useState(false);
  const key = `${s.score[0]}-${s.score[1]}`;
  const lastKey = useRef(key);
  useEffect(() => {
    // Pulse when the score changes during a replay - not on every page load.
    if (lastKey.current === key) return;
    lastKey.current = key;
    setBump(true);
    const t = setTimeout(() => setBump(false), 450);
    return () => clearTimeout(t);
  }, [key]);
  const replaying = !!s.live && (s.replay?.status === "running" || s.replay?.status === "paused");
  return (
    <section className={clsx("turf relative overflow-hidden rounded-3xl border", s.live ? "border-replay/40" : "border-rule")}>
      <div className="absolute inset-x-0 top-0 h-[3px] bg-gradient-to-r from-home via-grass to-away" aria-hidden />
      <div className="flex flex-wrap items-center justify-center gap-2 px-4 pt-5">
        <Link to={`/competitions/${s.competition.id}/${s.season.id}`} className="chip gap-2 bg-night/40 hover:text-chalk">
          <CompetitionMark name={s.competition.name} size={16} />{s.competition.name} · {s.stage || s.season.name}
        </Link>
        <span className="chip bg-night/40">{s.live ? "Originally played " : ""}{longDate(s.date)}</span>
        {s.live && <ReplayBadge status={s.replay?.status ?? "running"} minute={s.clock?.minute} />}
        {replaying && <ConnectionBadge c={connection} />}
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 px-3 py-6 sm:gap-4 sm:px-8">
        <Link to={`/team/${s.home.id}`} className="group flex min-w-0 flex-col items-center gap-2 text-center sm:flex-row sm:text-left">
          <Crest name={s.home.name} size={56} className="drop-shadow-lg" />
          <span className="min-w-0">
            <span className="block font-display text-lg uppercase leading-none group-hover:text-home sm:text-4xl [overflow-wrap:anywhere]">{s.home.name}</span>
            {s.home.manager && <span className="mt-1 hidden truncate text-[12px] text-dim sm:block">{s.home.manager}</span>}
          </span>
        </Link>
        <div className="text-center" aria-live="polite" aria-atomic="true">
          <p className={clsx("rounded-2xl bg-night/80 px-4 py-2 font-display text-5xl leading-none ring-1 ring-white/10 num transition-transform sm:px-6 sm:text-8xl",
            bump && "scale-105 text-signal")}>
            {s.score[0]}<span className="mx-1.5 text-dim sm:mx-3">-</span>{s.score[1]}
          </p>
          <p className={clsx("mt-2 font-mono text-[12.5px] font-bold uppercase tracking-wider", s.live && s.status !== "finished" ? "text-replay" : "text-mute")}>{clockLabel(s)}</p>
          {s.shootout && <p className="font-mono text-[12px] text-chalk">{s.shootout[0]}-{s.shootout[1]} on penalties</p>}
          {!s.live && s.halfTime && <p className="font-mono text-[11px] text-dim">HT {s.halfTime[0]}-{s.halfTime[1]}</p>}
        </div>
        <Link to={`/team/${s.away.id}`} className="group flex min-w-0 flex-col-reverse items-center gap-2 text-center sm:flex-row sm:text-right">
          <span className="min-w-0">
            <span className="block font-display text-lg uppercase leading-none group-hover:text-away sm:text-4xl [overflow-wrap:anywhere]">{s.away.name}</span>
            {s.away.manager && <span className="mt-1 hidden truncate text-[12px] text-dim sm:block">{s.away.manager}</span>}
          </span>
          <Crest name={s.away.name} size={56} className="drop-shadow-lg" />
        </Link>
      </div>
      <div className="grid grid-cols-2 gap-4 border-t border-white/5 bg-night/30 px-4 py-3 sm:px-8">
        <Scorers s={s} home />
        <Scorers s={s} home={false} />
      </div>
    </section>
  );
}

/** On a replay: this match was played on <date>; here is what really happened. */
function ReplayBanner({ s }: { s: MatchState }) {
  const nav = useNavigate();
  const r = s.replay;
  const restart = useMutation({
    mutationFn: () => api.replayStart(Number(r?.of), r?.speed || 60, true),
    onSuccess: (res) => nav(`/match/${res.matchId}?starting=1`, { replace: true }),
  });
  if (!r) return null;
  const o = r.original;
  const real = o.score ? `${s.home.name} ${o.score[0]}-${o.score[1]} ${s.away.name}` : null;
  const pens = o.shootout
    ? `, ${o.shootout[0] > o.shootout[1] ? s.home.name : s.away.name} won ${Math.max(...o.shootout)}-${Math.min(...o.shootout)} on penalties`
    : "";
  const playing = r.status === "running" || r.status === "paused";
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-replay/40 bg-replay/[.08] px-4 py-3 text-[13.5px]">
      <p className="min-w-0 flex-1 text-[#E4DAFF]">
        <b className="text-replay">{playing ? "You are watching a replay." : r.status === "finished" ? "This replay has reached full time." : "This replay was stopped."}</b>{" "}
        This match was played on {longDate(o.date || s.date)}.{real && <> The real result: <b className="text-chalk">{real}{pens}</b>.</>}
        {playing && r.speed ? ` Playing at ${r.speed}×.` : ""}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {!playing && (
          <button className="btn btn-replay" onClick={() => restart.mutate()} disabled={restart.isPending}>
            {restart.isPending ? "Starting…" : "Replay again"}
          </button>
        )}
        <Link className="btn" to={`/match/${r.of}`}>Full-time record →</Link>
      </div>
    </div>
  );
}

/** On an archived match: start a replay of it and go and watch. */
function WatchReplay({ id }: { id: string }) {
  const nav = useNavigate();
  const start = useMutation({
    mutationFn: () => api.replayStart(Number(id), 60, true),
    onSuccess: (r) => nav(`/match/${r.matchId}?starting=1`),
  });
  return (
    <button className="btn btn-replay" onClick={() => start.mutate()} disabled={start.isPending}
      title="Re-run this match minute by minute at 60×, with a synthesised VAR check">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden><path d="M7 4v16l13-8z" /></svg>
      {start.isPending ? "Starting…" : start.error ? "Replay service unavailable - try again" : "Watch the replay"}
    </button>
  );
}

/** Between pressing "Watch the replay" and the first events being projected. */
function WarmingUp() {
  return (
    <div className="turf grid place-items-center rounded-3xl border border-replay/40 px-6 py-16 text-center" role="status">
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#B79CFF" strokeWidth={2.2} strokeLinecap="round" className="animate-[spin_1.6s_linear_infinite]" aria-hidden>
        <path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" />
      </svg>
      <p className="mt-4 font-display text-2xl uppercase">Setting up the replay</p>
      <p className="mt-1 max-w-md text-[13.5px] text-mute">Loading the match's events and lining them up for kick-off. This takes a few seconds.</p>
    </div>
  );
}

const FLASH_TITLE: Record<string, string> = {
  disallow: "Goal disallowed", reinstate: "Goal reinstated", reassign: "Goal reassigned", amend: "Detail corrected",
};

function CorrectionBanner({ kind, message, synthesised, onClose }: { kind: string; message: string; synthesised: boolean; onClose: () => void }) {
  const scoring = kind === "disallow" || kind === "reinstate";
  return (
    <>
      <div className="pointer-events-none fixed inset-0 z-40 animate-sweep bg-[linear-gradient(105deg,transparent_40%,rgba(255,197,61,.30)_50%,transparent_60%)] bg-[length:300%_100%] opacity-0" aria-hidden />
      <div role="alert" className="flex animate-slam items-start gap-3 rounded-2xl border border-signal/50 bg-gradient-to-b from-signal/15 to-signal/5 p-4">
        <span className="mt-0.5 h-5 w-7 shrink-0 rounded-[3px] border-[2.5px] border-signal" aria-hidden />
        <div className="flex-1">
          <p className="text-[14px] font-extrabold text-signal">{FLASH_TITLE[kind] ?? "Correction"}</p>
          <p className="text-[13.5px] text-[#F2E4C0]">
            {message}{" "}
            {scoring
              ? "The goal stays in the log, struck through. The win probability, the report and the stats have all been rebuilt from the corrected log."
              : "Nothing was overwritten: the original value stays in the log, and every number that depended on it was recomputed."}
          </p>
          {synthesised && <p className="mt-1 text-[12px] text-dim">This decision was synthesised for the replay - StatsBomb open data records no VAR calls.</p>}
        </div>
        <button onClick={onClose} className="text-dim hover:text-chalk" aria-label="Dismiss">✕</button>
      </div>
    </>
  );
}

/** "Was it ever 2-1?" - scrub to any minute and ask the append-only log. */
function ScoreAt({ s }: { s: MatchState }) {
  const [minute, setMinute] = useState(45);
  const period = minute <= 45 ? 1 : minute <= 90 ? 2 : minute <= 105 ? 3 : 4;
  const { data } = useQuery({ queryKey: ["score-at", s.id, minute, s.version], queryFn: () => api.scoreAt(s.id, period, minute) });
  const max = s.live ? Math.max(1, s.clock?.minute ?? 1) : s.timeline.some((t) => t.period >= 3) ? 120 : 90;
  return (
    <div className="panel p-4">
      <p className="eyebrow mb-2">What was the score at…</p>
      <div className="flex items-center gap-3">
        <input id="score-at" type="range" min={0} max={max} value={Math.min(minute, max)} onChange={(e) => setMinute(Number(e.target.value))}
          className="flex-1 accent-grass" aria-label="Minute" />
        <span className="w-12 text-right font-mono text-[13px] num">{Math.min(minute, max)}'</span>
        <span className="rounded-lg bg-deck2 px-3 py-1 font-display text-xl num">{data ? `${data.score[0]}-${data.score[1]}` : "…"}</span>
      </div>
      <p className="mt-2 text-[12px] text-dim">Answered from the append-only log. A goal that was later disallowed still counts at the minutes when it stood - which is exactly what a scores site that overwrites the number cannot tell you.</p>
    </div>
  );
}

function Lineups({ s }: { s: MatchState }) {
  if (!s.lineups.home.length) return <p className="text-[13px] text-mute">No lineups were published for this match.</p>;
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,26rem)_1fr]">
      <div>
        <FormationPitch home={s.lineups.home} away={s.lineups.away} homeName={s.home.name} awayName={s.away.name} />
        <p className="mt-2 text-[12px] text-dim">
          Starting positions as recorded by StatsBomb: <span className="text-away">{s.away.name}</span> at the top,{" "}
          <span className="text-home">{s.home.name}</span> at the bottom.
        </p>
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        {(["home", "away"] as const).map((side) => (
          <div key={side}>
            <p className={clsx("mb-1 flex items-center gap-2 font-display uppercase tracking-wide", side === "home" ? "text-home" : "text-away")}>
              <Crest name={s[side].name} size={20} />{s[side].name}
            </p>
            {s[side].manager && <p className="mb-2 text-[12px] text-dim">Manager: {s[side].manager}</p>}
            {([["Starting XI", true], ["Substitutes", false]] as const).map(([label, started]) => (
              <div key={label} className="mb-3">
                <p className="eyebrow mb-1">{label}</p>
                <ul className="divide-y divide-rule/50 text-[13px]">
                  {s.lineups[side].filter((p) => p.started === started).map((p) => (
                    <li key={p.id} className={clsx("flex items-center gap-3 py-1.5", !p.started && "text-mute")}>
                      <span className={clsx("grid h-5 w-5 shrink-0 place-items-center rounded-full font-mono text-[10px] font-bold num",
                        side === "home" ? "bg-home/20 text-home" : "bg-away/20 text-away")}>{p.number ?? ""}</span>
                      <Link to={`/player/${p.id}`} className="truncate font-bold hover:text-grass">{p.name}</Link>
                      <span className="ml-auto shrink-0 truncate text-[11.5px] text-dim">{p.started ? p.position : ""}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Match() {
  const { mid = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (TABS as readonly string[]).includes(params.get("tab") ?? "") ? (params.get("tab") as Tab) : "summary";
  const isLive = mid.startsWith("live-");

  const starting = isLive && params.get("starting") === "1";
  // A replay that was just requested has no document yet (or a stale one from
  // an earlier run). Watch the replay service until this run is playing, and
  // only then load the match.
  const warm = useQuery({
    queryKey: ["replay-warm", mid], queryFn: api.replayStatus, enabled: starting,
    refetchInterval: (q) => (q.state.data?.find((r) => r.matchId === mid)?.status === "running" ? false : 1000),
  });
  const ready = !starting || warm.data?.find((r) => r.matchId === mid)?.status === "running";
  const qc = useQueryClient();
  useEffect(() => {
    // Anything cached for this id belongs to an earlier run of the replay.
    if (starting) for (const k of ["match", "wp", "report", "shots", "pass", "score-at"]) qc.removeQueries({ queryKey: [k, mid] });
  }, [starting, mid, qc]);
  const state = useQuery({
    queryKey: ["match", mid], queryFn: () => api.match(mid), enabled: ready,
    // The first projection can land a moment after the run starts.
    retry: (n, e) => (starting && e instanceof ApiError && e.status === 404 ? n < 10 : n < 2),
    retryDelay: 1000,
    refetchInterval: isLive ? 20_000 : false,
  });
  const [gaveUp, setGaveUp] = useState(false);
  useEffect(() => {
    if (!starting) return;
    setGaveUp(false);
    const t = setTimeout(() => setGaveUp(true), 45_000);
    return () => clearTimeout(t);
  }, [starting]);
  // Parts of a replay that is still warming up do not exist yet.
  const partsReady = ready && (!starting || !!state.data);
  const wp = useQuery({ queryKey: ["wp", mid], queryFn: () => api.winProbability(mid), enabled: partsReady });
  const report = useQuery({ queryKey: ["report", mid], queryFn: () => api.report(mid), enabled: partsReady });
  const shots = useQuery({ queryKey: ["shots", mid], queryFn: () => api.shots(mid), enabled: partsReady && (tab === "shots" || tab === "summary") });
  const netHome = useQuery({ queryKey: ["pass", mid, "home"], queryFn: () => api.passNetwork(mid, "home"), enabled: partsReady && tab === "passing" });
  const netAway = useQuery({ queryKey: ["pass", mid, "away"], queryFn: () => api.passNetwork(mid, "away"), enabled: partsReady && tab === "passing" });
  const replayPlaying = state.data?.replay?.status === "running" || state.data?.replay?.status === "paused";
  const live = useLiveMatch(mid, isLive && !!state.data && replayPlaying, state.data?.seq ?? 0);

  useEffect(() => {
    // Once the replay is playing, drop ?starting so a reload behaves normally.
    if (starting && state.data?.replay?.status === "running") {
      const next = new URLSearchParams(params); next.delete("starting");
      setParams(next, { replace: true });
    }
  }, [starting, state.data, params, setParams]);

  useEffect(() => {
    if (state.data) document.title = `${state.data.home.name} ${state.data.score[0]}-${state.data.score[1]} ${state.data.away.name} · Onside`;
    return () => { document.title = "Onside"; };
  }, [state.data]);

  const current = useMemo(() => {
    const s = state.data;
    if (!s || !wp.data?.series.length) return null;
    const m = s.live ? Math.min(s.clock?.minute ?? 0, 90) : 90;
    return wp.data.series.find((p) => p.minute === m) ?? wp.data.series[wp.data.series.length - 1];
  }, [state.data, wp.data]);

  if (starting && !gaveUp && (!ready || !state.data) && !(state.error && !(state.error instanceof ApiError && state.error.status === 404))) {
    return <WarmingUp />;
  }
  if (starting && gaveUp && !state.data) {
    return <ErrorState error={new ApiError(503, "replay_timeout",
      "The replay service has not picked this replay up. If you are running Onside yourself, check that the replay container is up, then try again.")} />;
  }
  if (state.isLoading) return <PageSkeleton />;
  if (state.error || !state.data) return <ErrorState error={state.error} retry={state.refetch} />;
  const s = state.data;
  const corrected = s.corrections.length > 0;

  return (
    <div className="space-y-4">
      <Scoreboard s={s} connection={live.connection} />
      {s.live && <ReplayBanner s={s} />}
      {live.flash && <CorrectionBanner kind={live.flash.kind} message={live.flash.message} synthesised={live.flash.synthesised} onClose={live.dismiss} />}
      {!live.flash && corrected && (
        <div className="rounded-2xl border border-signal/40 bg-signal/[.07] px-4 py-3 text-[13px] text-[#F2E4C0]">
          {s.corrections.map((c) => <p key={c.id}><b className="text-signal">{c.decidedAt}'</b> — {c.headline}{c.synthesised && " (synthesised for this replay)"}</p>)}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
      <nav className="-mx-4 flex flex-1 gap-1 overflow-x-auto px-4 scroll-x sm:mx-0 sm:px-0" role="tablist" aria-label="Match sections">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setParams(t === "summary" ? {} : { tab: t }, { replace: true })}
            className={clsx("shrink-0 rounded-full px-4 py-2 text-[13px] font-bold capitalize transition", tab === t ? "bg-grass text-[#03170A]" : "text-mute hover:text-chalk")}>
            {t}
          </button>
        ))}
      </nav>
      {!s.live && <WatchReplay id={s.id} />}
      </div>

      {tab === "summary" && (
        <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
          <div className="space-y-4">
            <section className="panel overflow-hidden">
              <div className="panel-head">
                <h2 className="h-section">Win probability</h2>
                <span className="text-[11.5px] text-dim">{s.live && s.status !== "finished" && (s.clock?.minute ?? 0) > 90 ? "Extra time is outside the model - it is trained on 90 minutes." : "Recomputed from the match state every minute"}</span>
              </div>
              <div className="px-2 pt-3">
                {wp.data ? <WinProbabilityChart series={wp.data.series} goals={s.goals} home={s.home.name} away={s.away.name}
                  upToMinute={s.live ? s.clock?.minute : undefined} /> : <Skeleton className="m-2 h-64" />}
              </div>
              {current && (
                <dl className="grid grid-cols-3 border-t border-rule text-center">
                  {([[s.home.name, current.p_home, "text-home"], ["Draw", current.p_draw, "text-mute"], [s.away.name, current.p_away, "text-away"]] as const).map(([k, v, c]) => (
                    <div key={k} className="border-r border-rule px-2 py-3 last:border-0">
                      <dt className="eyebrow truncate">{k}</dt>
                      <dd className={clsx("font-display text-3xl num", c)}>{Math.round(v * 100)}%</dd>
                    </div>
                  ))}
                </dl>
              )}
              <p className="border-t border-rule px-4 py-2 text-[11.5px] text-dim">
                {s.live ? "During the replay" : "At full time of regulation"}: a LightGBM model trained on 288,288 match-minutes, calibrated on 793 later matches. <Link className="link" to="/about">How it's checked</Link>
              </p>
            </section>
            <ScoreAt s={s} />
          </div>
          <div className="space-y-4">
            <section className="panel p-4">
              {report.data ? <ReportView report={report.data} corrected={corrected} synthesised={s.corrections.some((c) => c.synthesised)} /> : <Skeleton className="h-64" />}
            </section>
          </div>
        </div>
      )}
      {tab === "timeline" && <section className="panel overflow-hidden"><Timeline state={s} /></section>}
      {tab === "stats" && <section className="panel p-5"><StatBars state={s} /><p className="mt-5 text-[12px] text-dim">Hover or tap a stat for what it means. {s.home.name} left, {s.away.name} right; the stronger figure is highlighted.</p></section>}
      {tab === "shots" && <section className="panel p-4">{shots.data ? <ShotMap shots={shots.data} /> : shots.error ? <ErrorState error={shots.error} /> : <Skeleton className="h-80" />}</section>}
      {tab === "passing" && (
        <div className="grid gap-4 lg:grid-cols-2">
          {([["home", netHome], ["away", netAway]] as const).map(([side, q]) => (
            <section key={side} className="panel p-4">
              <h2 className={clsx("mb-3 font-display uppercase tracking-wide", side === "home" ? "text-home" : "text-away")}>{s[side].name}</h2>
              {q.data ? <PassNetworkView net={q.data} home={side === "home"} /> : <Skeleton className="h-64" />}
            </section>
          ))}
        </div>
      )}
      {tab === "report" && <section className="panel p-5">{report.data ? <ReportView report={report.data} corrected={corrected} synthesised={s.corrections.some((c) => c.synthesised)} /> : <Skeleton className="h-64" />}</section>}
      {tab === "lineups" && <section className="panel p-5"><Lineups s={s} /></section>}

      <p className="text-[12px] text-dim">
        {s.eventCount.toLocaleString()} events · {s.stadium && `${s.stadium} · `}{s.referee && `Referee ${s.referee} · `}
        <a className="link" href={`/m/${s.id}`}>Plain page for slow connections</a> · <a className="link" href={`/api/matches/${s.id}`}>JSON</a>
      </p>
    </div>
  );
}
