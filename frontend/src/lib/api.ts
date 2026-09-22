import type {
  ApiErrorBody, Competition, Home, LeaderboardRow, MatchCard, MatchState, Page, PassNetwork,
  CurrentCompetition, CurrentScorers, CurrentStandings, Network, Player, PlayerSeason, ReplayStatus, Report,
  SearchResult, Shot, SocialOverview, SocialPost, Table, Team, Today, WpPoint,
} from "./types";

/** An API failure carrying the server's plain-English message. The UI shows
 *  `message` directly - the API writes it for people, not for developers. */
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public detail: Record<string, unknown> = {}) {
    super(message);
  }
}

const BASE = import.meta.env.VITE_API_BASE ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "network", "Onside's server could not be reached. Check your connection - the page will retry on its own.");
  }
  if (!res.ok) {
    let body: ApiErrorBody | null = null;
    try { body = await res.json(); } catch { /* not JSON - fall through */ }
    throw new ApiError(res.status, body?.error ?? "http_error",
      body?.message ?? `The server answered ${res.status}. Try again in a moment.`, body?.detail ?? {});
  }
  return res.json() as Promise<T>;
}

const q = (params: Record<string, string | number | boolean | null | undefined>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") s.set(k, String(v));
  const str = s.toString();
  return str ? `?${str}` : "";
};

export const api = {
  home: () => request<Home>("/api/home"),
  live: () => request<MatchCard[]>("/api/live"),
  today: () => request<Today>("/api/today"),
  currentCompetitions: () => request<CurrentCompetition[]>("/api/current/competitions"),
  currentStandings: (code: string) => request<CurrentStandings>(`/api/current/${code}/standings`),
  currentScorers: (code: string) => request<CurrentScorers>(`/api/current/${code}/scorers`),
  social: (p: { topic?: string; network?: Network | ""; lang?: string; before?: number | null; limit?: number } = {}) =>
    request<{ items: SocialPost[]; next: number | null }>(`/api/social${q({ topic: p.topic, network: p.network, lang: p.lang, before: p.before, limit: p.limit ?? 30 })}`),
  socialOverview: () => request<SocialOverview>("/api/social/overview"),
  feed: (p: { tag?: string; cursor?: string | null; limit?: number } = {}) =>
    request<Page<MatchCard>>(`/api/feed${q({ tag: p.tag, cursor: p.cursor, limit: p.limit ?? 24 })}`),
  collection: (id: string) => request<{ id: string; title: string; blurb: string; matches: MatchCard[] }>(`/api/collections/${id}`),
  search: (term: string) => request<SearchResult[]>(`/api/search${q({ q: term })}`),
  competitions: () => request<Competition[]>("/api/competitions"),
  competition: (id: string) => request<Competition>(`/api/competitions/${id}`),
  seasonMatches: (cid: string, sid: string) => request<MatchCard[]>(`/api/competitions/${cid}/seasons/${sid}/matches`),
  tables: (cid: string, sid: string) =>
    request<{ tables: Table[]; note: string }>(`/api/competitions/${cid}/table${q({ season: sid })}`),
  match: (id: string) => request<MatchState>(`/api/matches/${id}`),
  report: (id: string) => request<Report>(`/api/matches/${id}/report`),
  winProbability: (id: string) => request<{ matchId: string; range: string; series: WpPoint[] }>(`/api/matches/${id}/win-probability`),
  shots: (id: string) => request<Shot[]>(`/api/matches/${id}/shots`),
  passNetwork: (id: string, team: "home" | "away") => request<PassNetwork>(`/api/matches/${id}/pass-network${q({ team })}`),
  scoreAt: (id: string, period: number, minute: number) =>
    request<{ score: [number, number]; note: string }>(`/api/matches/${id}/score-at${q({ period, minute })}`),
  team: (id: string) => request<Team>(`/api/teams/${id}`),
  teamMatches: (id: string, cursor?: string | null) => request<Page<MatchCard>>(`/api/teams/${id}/matches${q({ cursor, limit: 30 })}`),
  teamForm: (id: string) => request<{ form: { matchId: string; opponent: string; result: string; score: string; date: string }[] }>(`/api/teams/${id}/form`),
  player: (id: string) => request<Player>(`/api/players/${id}`),
  playerSeasons: (id: string) => request<{ player: Player; seasons: PlayerSeason[]; queryMs: number }>(`/api/players/${id}/seasons`),
  playerShots: (id: string) => request<{ matchId: number; date: string; minute: number; x: number; y: number; xg: number; outcome: string; type: string }[]>(`/api/players/${id}/shots`),
  metrics: () => request<{ id: string; description: string }[]>("/api/analytics/metrics"),
  leaderboard: (p: { metric: string; competition?: string; season?: string }) =>
    request<{ metric: string; description: string; rows: LeaderboardRow[]; queryMs: number }>(
      `/api/analytics/leaderboard${q({ metric: p.metric, competition: p.competition, season: p.season, limit: 50 })}`),
  replayStatus: () => request<ReplayStatus[]>("/api/replay/status"),
  replayStart: (matchId: number, speed: number, injectVar: boolean) =>
    request<ReplayStatus>("/api/replay/start", { method: "POST", body: JSON.stringify({ match_id: matchId, speed, inject_var: injectVar }) }),
  replayCommand: (cmd: "pause" | "resume" | "stop" | "speed", matchId: string, speed?: number) =>
    request<ReplayStatus>(`/api/replay/${cmd}`, { method: "POST", body: JSON.stringify({ match_id: matchId, speed }) }),
};
