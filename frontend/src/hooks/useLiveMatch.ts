import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { MatchState, Report, WpPoint } from "../lib/types";

export type Connection = "connecting" | "live" | "reconnecting" | "closed";

export interface CorrectionFlash {
  id: string;
  kind: string;
  message: string;
  scoreBefore: [number, number];
  scoreAfter: [number, number];
  synthesised: boolean;
  at: number;
}

export interface Msg {
  type: string; seq: number; channel: string;
  score?: [number, number]; shootout?: [number, number] | null; status?: MatchState["status"];
  clock?: MatchState["clock"]; stats?: MatchState["stats"]; version?: number;
  items?: MatchState["timeline"]; report?: Report;
  point?: WpPoint; minute?: number; series?: WpPoint[] | null;
  correction?: MatchState["corrections"][number]; message?: string;
  scoreBefore?: [number, number]; scoreAfter?: [number, number];
}

function wsUrl(path: string): string {
  const base = import.meta.env.VITE_WS_BASE as string | undefined;
  if (base) return `${base}${path}`;
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}${path}`;
}

/**
 * Subscribes to a live match and folds the server's *diffs* into the query
 * cache, so every component reading the match re-renders with the new state.
 *
 * Resumable: the last `seq` seen is kept, and a reconnect asks for `?since=`
 * that seq - the server replays what was missed from its channel log, so a
 * dropped connection loses nothing. Reconnects back off exponentially.
 */
export function useLiveMatch(matchId: string | undefined, enabled: boolean, startSeq = 0) {
  const qc = useQueryClient();
  const [connection, setConnection] = useState<Connection>("closed");
  const [flash, setFlash] = useState<CorrectionFlash | null>(null);
  // Start from the sequence the fetched state already reflects, so the
  // channel's history is not replayed on top of it.
  const seq = useRef(startSeq);
  const caughtUp = useRef(false);

  useEffect(() => {
    if (!matchId || !enabled) return;
    let ws: WebSocket | null = null;
    let attempt = 0;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const apply = (m: Msg) => {
      if (m.seq) seq.current = Math.max(seq.current, m.seq);
      switch (m.type) {
        case "state_changed":
          qc.setQueryData<MatchState>(["match", matchId], (old) => old && {
            ...old, score: m.score ?? old.score, shootout: m.shootout ?? old.shootout,
            status: m.status ?? old.status, clock: m.clock ?? old.clock,
            stats: m.stats ?? old.stats, version: m.version ?? old.version,
          });
          break;
        case "event_appended":
          qc.setQueryData<MatchState>(["match", matchId], (old) => old && {
            ...old, timeline: [...old.timeline, ...(m.items ?? [])],
          });
          break;
        case "wp_updated":
          qc.setQueryData<{ series: WpPoint[]; range: string; matchId: string }>(["wp", matchId], (old) => {
            if (!old) return old;
            if (m.series) return { ...old, series: m.series };
            const series = old.series.filter((p) => p.minute !== m.minute);
            if (m.point) series.push(m.point);
            series.sort((a, b) => a.minute - b.minute);
            return { ...old, series };
          });
          break;
        case "report_regenerated":
          if (m.report) qc.setQueryData(["report", matchId], m.report);
          break;
        case "hello":
          caughtUp.current = true;
          break;
        case "correction_applied":
          // Only announce corrections that land while the viewer is watching;
          // anything replayed from the backlog is already in the refetched state.
          if (caughtUp.current) setFlash({
            id: m.correction?.id ?? String(m.seq), kind: m.correction?.kind ?? "amend",
            message: m.message ?? "A correction was applied.",
            scoreBefore: m.scoreBefore ?? [0, 0], scoreAfter: m.scoreAfter ?? [0, 0],
            synthesised: !!m.correction?.synthesised, at: Date.now(),
          });
          // A correction rewrites history: refetch the full state and series.
          qc.invalidateQueries({ queryKey: ["match", matchId] });
          qc.invalidateQueries({ queryKey: ["wp", matchId] });
          qc.invalidateQueries({ queryKey: ["shots", matchId] });
          break;
        case "replay_restarted":
          seq.current = m.seq;
          setFlash(null);
          qc.invalidateQueries({ queryKey: ["match", matchId] });
          qc.invalidateQueries({ queryKey: ["wp", matchId] });
          qc.invalidateQueries({ queryKey: ["report", matchId] });
          break;
      }
    };

    const connect = () => {
      caughtUp.current = false;
      setConnection(attempt === 0 ? "connecting" : "reconnecting");
      ws = new WebSocket(wsUrl(`/ws/match/${matchId}?since=${seq.current}`));
      ws.onopen = () => { attempt = 0; setConnection("live"); };
      ws.onmessage = (ev) => { try { apply(JSON.parse(ev.data) as Msg); } catch { /* ignore malformed */ } };
      ws.onclose = () => {
        if (stopped) return;
        setConnection("reconnecting");
        const delay = Math.min(15_000, 500 * 2 ** attempt++) + Math.random() * 300;
        timer = setTimeout(connect, delay);
      };
      ws.onerror = () => ws?.close();
    };
    connect();
    return () => { stopped = true; clearTimeout(timer); ws?.close(); setConnection("closed"); };
    // startSeq is read once per subscription on purpose: later state refetches
    // must not restart the socket.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchId, enabled, qc]);

  // The banner is the moment; the permanent record is the corrections list
  // under the scoreboard. Let the moment pass on its own.
  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 15_000);
    return () => clearTimeout(t);
  }, [flash]);

  return { connection, flash, dismiss: () => setFlash(null) };
}

/** Score changes across every live match, for the ticker. */
export function useFeedSocket(onScore: (card: unknown) => void) {
  useEffect(() => {
    let ws: WebSocket | null = null;
    let stopped = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const connect = () => {
      ws = new WebSocket(wsUrl("/ws/feed"));
      ws.onmessage = (ev) => {
        try { const m = JSON.parse(ev.data); if (m.type === "score_changed") onScore(m.card); } catch { /* ignore */ }
      };
      ws.onopen = () => { attempt = 0; };
      ws.onclose = () => { if (!stopped) timer = setTimeout(connect, Math.min(15_000, 1000 * 2 ** attempt++)); };
    };
    connect();
    return () => { stopped = true; clearTimeout(timer); ws?.close(); };
  }, [onScore]);
}
