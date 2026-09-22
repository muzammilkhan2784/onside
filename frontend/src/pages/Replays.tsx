import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { api, ApiError } from "../lib/api";
import { longDate } from "../lib/format";
import type { ReplayStatus } from "../lib/types";
import { CompetitionMark, Crest, ReplayBadge } from "../components/Football";

/** Finals and classics that make good replays. Every id is in the archive. */
const PICKS = [
  { id: 3869685, home: "Argentina", away: "France", comp: "FIFA World Cup", stage: "Final", date: "2022-12-18" },
  { id: 3943043, home: "Spain", away: "England", comp: "UEFA Euro", stage: "Final", date: "2024-07-14" },
  { id: 4020846, home: "England Women's", away: "Spain Women's", comp: "UEFA Women's Euro", stage: "Final", date: "2025-07-27" },
  { id: 18245, home: "Real Madrid", away: "Liverpool", comp: "Champions League", stage: "Final", date: "2018-05-26" },
  { id: 22912, home: "Tottenham Hotspur", away: "Liverpool", comp: "Champions League", stage: "Final", date: "2019-06-01" },
  { id: 3750201, home: "Barcelona", away: "Manchester United", comp: "Champions League", stage: "Final", date: "2009-05-27" },
];

const SPEEDS = [
  { v: 30, label: "30×", note: "about 4 minutes a match" },
  { v: 60, label: "60×", note: "about 2 minutes" },
  { v: 120, label: "120×", note: "about a minute" },
  { v: 10, label: "10×", note: "about 12 minutes" },
];

function Running({ r, onCommand }: { r: ReplayStatus; onCommand: (cmd: "pause" | "resume" | "stop" | "speed", speed?: number) => void }) {
  const playing = r.status === "running" || r.status === "paused";
  const [home, away] = (r.title || "").split(" v ");
  return (
    <li className="flex flex-wrap items-center gap-3 px-4 py-3">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <div className="flex -space-x-1.5">{home && <Crest name={home} size={26} />}{away && <Crest name={away} size={26} />}</div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link to={`/match/${r.matchId}`} className="truncate font-bold hover:text-replay">{r.title || r.matchId}</Link>
            <ReplayBadge status={r.status} minute={r.minute} />
          </div>
          <p className="mt-0.5 text-[12px] text-dim">
            {playing ? `${r.minute}' · ${r.speed}× · ` : ""}{r.sent.toLocaleString()} of {r.total.toLocaleString()} events
          </p>
          <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-deck2">
            <div className={clsx("h-full", playing ? "bg-replay" : "bg-dim")} style={{ width: `${(r.sent / Math.max(1, r.total)) * 100}%` }} />
          </div>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {playing && (r.status === "paused"
          ? <button className="btn" onClick={() => onCommand("resume")}>Resume</button>
          : <button className="btn" onClick={() => onCommand("pause")}>Pause</button>)}
        {playing && <button className="btn" onClick={() => onCommand("speed", r.speed >= 120 ? 30 : r.speed * 2)}>Speed ×2</button>}
        {playing && <button className="btn" onClick={() => onCommand("stop")}>Stop</button>}
        <Link className={clsx("btn", playing && "btn-replay")} to={`/match/${r.matchId}`}>{playing ? "Watch" : "Open"}</Link>
      </div>
    </li>
  );
}

/** The replay room: re-run any archived match minute by minute, clearly
 *  labelled as a replay, through the same pipeline a live feed would use. */
export default function Replays() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const status = useQuery({ queryKey: ["replays"], queryFn: api.replayStatus, refetchInterval: 2000 });
  const [pick, setPick] = useState<number>(PICKS[0].id);
  const [custom, setCustom] = useState("");
  const [speed, setSpeed] = useState(60);
  const [inject, setInject] = useState(true);
  const matchId = custom ? Number(custom) : pick;
  const start = useMutation({
    mutationFn: () => api.replayStart(matchId, speed, inject),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["replays"] }); nav(`/match/${r.matchId}?starting=1`); },
  });
  const command = useMutation({
    mutationFn: (p: { cmd: "pause" | "resume" | "stop" | "speed"; id: string; speed?: number }) => api.replayCommand(p.cmd, p.id, p.speed),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["replays"] }),
  });
  const rows = status.data ?? [];

  return (
    <div className="space-y-6">
      <section className="turf relative overflow-hidden rounded-3xl border border-rule p-6 sm:p-8">
        <ReplayBadge status="idle" className="mb-3" />
        <h1 className="font-display text-4xl uppercase leading-none sm:text-6xl">Replay room</h1>
        <p className="mt-3 max-w-2xl text-[15px] text-[#CFE0D4]">
          Every match on Onside has already been played. Pick one and it is re-run minute by minute through the same
          pipeline a live feed uses - Redis Streams, the ingest workers, the append-only log, a WebSocket to your
          browser - so you can watch a VAR decision correct the score, the model and the report as it lands.
        </p>
        <p className="mt-2 text-[13px] text-mute">A replay is always marked <b className="text-replay">Replay</b>, and its page shows the real result. The archived match is never changed.</p>
      </section>

      <section className="panel p-5">
        <h2 className="h-section mb-4">1 · Pick a match</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {PICKS.map((p) => (
            <button key={p.id} onClick={() => { setPick(p.id); setCustom(""); }} aria-pressed={!custom && pick === p.id}
              className={clsx("rounded-2xl border p-4 text-left transition",
                !custom && pick === p.id ? "border-replay bg-replay/10" : "border-rule bg-deck2/40 hover:border-mute")}>
              <span className="flex items-center gap-2"><CompetitionMark name={p.comp} size={18} /><span className="eyebrow text-mute">{p.comp} · {p.stage}</span></span>
              <span className="mt-3 flex items-center gap-2 font-bold"><Crest name={p.home} size={20} />{p.home}</span>
              <span className="mt-1 flex items-center gap-2 font-bold"><Crest name={p.away} size={20} />{p.away}</span>
              <span className="mt-2 block text-[12px] text-dim">Played {longDate(p.date)}</span>
            </button>
          ))}
        </div>
        <label className="mt-4 block text-[13px] text-mute">
          …or any match id from the archive
          <input id="replay-match" value={custom} onChange={(e) => setCustom(e.target.value.replace(/\D/g, ""))}
            className="mt-1 block w-full max-w-xs rounded-xl border border-rule bg-deck2 px-3 py-2 text-chalk" inputMode="numeric"
            placeholder="e.g. 3857256" />
          <span className="mt-1 block text-[12px] text-dim">Easier: open any match and press <b>Watch the replay</b>.</span>
        </label>
      </section>

      <section className="panel p-5">
        <h2 className="h-section mb-4">2 · Set it up</h2>
        <div className="flex flex-wrap items-end gap-6">
          <fieldset>
            <legend className="mb-1.5 text-[13px] text-mute">Speed</legend>
            <div className="flex flex-wrap gap-1.5">
              {SPEEDS.map((s) => (
                <button key={s.v} onClick={() => setSpeed(s.v)} aria-pressed={speed === s.v} title={s.note}
                  className={clsx("rounded-full border px-3 py-1.5 text-[13px] font-bold", speed === s.v ? "border-replay bg-replay/15 text-replay" : "border-rule text-mute hover:text-chalk")}>
                  {s.label}
                </button>
              ))}
            </div>
            <p className="mt-1 text-[12px] text-dim">{SPEEDS.find((s) => s.v === speed)?.note}</p>
          </fieldset>
          <label className="flex max-w-md items-start gap-2 text-[13px] text-mute">
            <input id="replay-var" type="checkbox" checked={inject} onChange={(e) => setInject(e.target.checked)} className="mt-0.5 accent-signal" />
            <span><b className="text-chalk">Add a VAR check.</b> StatsBomb's open data records no VAR decisions, so Onside synthesises one from the real events and labels it synthesised everywhere it appears.</span>
          </label>
          <button className="btn btn-replay ml-auto px-6 py-2.5 text-[14px]" onClick={() => start.mutate()} disabled={!matchId || start.isPending}>
            {start.isPending ? "Starting…" : "Start the replay →"}
          </button>
        </div>
        {start.error && <p className="mt-3 text-[13px] text-away">{start.error instanceof ApiError ? start.error.message : "Could not start the replay."}</p>}
      </section>

      <section className="panel overflow-hidden">
        <div className="panel-head"><h2 className="h-section">Replays</h2><span className="text-[12px] text-dim">Playing first, then ones that have ended</span></div>
        {status.error ? (
          <p className="p-4 text-[13px] text-mute">{status.error instanceof ApiError ? status.error.message : "Could not reach the replay service."}</p>
        ) : !rows.length ? (
          <p className="p-4 text-[13px] text-mute">Nothing has been replayed yet. Pick a match above and start one.</p>
        ) : (
          <ul className="divide-y divide-rule/60">
            {rows.map((r) => <Running key={r.matchId} r={r} onCommand={(cmd, s) => command.mutate({ cmd, id: r.matchId, speed: s })} />)}
          </ul>
        )}
      </section>
    </div>
  );
}
