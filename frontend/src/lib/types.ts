// Shapes returned by the Onside API. Kept in step with backend/onside/api/schemas.py
// and the match document built in backend/onside/ingest/document.py.

export interface Ref { id: string; name: string }

export interface MatchCard {
  id: string;
  competition: { id: string; name: string; gender?: string; international?: boolean };
  season: { id: string; name: string };
  date: string;
  kickoff: string;
  stage: string;
  matchWeek: number | null;
  home: Ref;
  away: Ref;
  score: [number, number];
  shootout: [number, number] | null;
  status: string;
  xg: [number | null, number | null];
  headline: string;
  standfirst: string;
  tags: string[];
  biggestSwing: number;
  hasFreezeFrames: boolean;
  live: boolean;
}

export interface Page<T> { items: T[]; next: string | null }

export interface Season { id: string; name: string; matches: number; from: string; to: string }

export interface Competition {
  id: string; name: string; country: string; gender: string;
  international: boolean; youth?: boolean; matches: number; seasons: Season[];
}

export interface Goal {
  eventId: string; period: number; minute: number; home: boolean; team: string;
  player: string; playerId: string; xg: number | null; type: string; ownGoal: boolean;
  disallowed: boolean; correctionReason?: string; correctedAt?: number | null;
  synthesisedCorrection?: boolean;
}

export interface TimelineItem {
  kind: "goal" | "own_goal" | "card" | "sub" | "big_chance" | "penalty_miss" | "shootout" | "correction";
  period: number; minute: number; second: number; home: boolean | null; team: string;
  player: string; detail: string; eventId: string; xg?: number | null;
  disallowed?: boolean; correctionReason?: string; correctedAt?: number;
  correctionKind?: string; authority?: string; supersedes?: string; synthesised?: boolean;
}

export interface TeamStats {
  teamId: string; team: string; goals: number; shots: number; shotsOnTarget: number;
  bigChances: number; xg: number; passes: number; passAccuracy: number;
  progressivePasses: number; finalThirdPasses: number; corners: number; fouls: number;
  yellowCards: number; redCards: number; possession: number; fieldTilt: number; ppda: number | null;
}

export interface Correction {
  id: string; supersedes: string; kind: string; reason: string; authority: string;
  period: number; decidedAt: number; synthesised: boolean; headline: string;
}

export interface LineupPlayer {
  id: string; name: string; number: number | null; position: string; started: boolean; country: string;
}

export interface MatchState {
  id: string;
  competition: MatchCard["competition"];
  season: Ref;
  date: string; kickoff: string; matchWeek: number | null; stage: string; stadium: string;
  referee: string; neutral: boolean;
  home: Ref & { country: string; manager: string };
  away: Ref & { country: string; manager: string };
  score: [number, number]; halfTime: [number, number]; shootout: [number, number] | null;
  status: "finished" | "live" | "half_time" | "scheduled";
  goals: Goal[]; cards: { eventId: string; minute: number; home: boolean; player: string; card: string }[];
  timeline: TimelineItem[];
  stats: { home: TeamStats; away: TeamStats };
  glossary: Record<string, string>;
  lineups: { home: LineupPlayer[]; away: LineupPlayer[] };
  capabilities: Record<string, string | boolean>;
  eventCount: number;
  corrections: Correction[];
  story: { headline: string; standfirst: string; tags: string[]; biggestSwing: number };
  live?: boolean;
  clock?: { period: number; minute: number; second: number };
  version?: number;
  /** Live matches: the channel sequence this state corresponds to. */
  seq?: number;
  /** Replays only: whether it is still playing, and the real archived result. */
  replay?: ReplayInfo;
}

export interface ReplayInfo {
  of: string;
  status: "running" | "paused" | "finished" | "stopped" | string;
  speed: number;
  minute: number;
  original: { date: string; score: [number, number] | null; shootout: [number, number] | null };
}

export interface WpPoint { minute: number; p_home: number; p_draw: number; p_away: number }

export interface Report {
  headline: string; lede: string; lines: string[]; closing: string; notes: string[];
  moments: { kind: string; period: number; minute: number; player: string; team: string;
             swing: number; before: number[]; after: number[] }[];
}

export interface FreezeActor { x: number; y: number; teammate: boolean; keeper: boolean; name: string }

export interface Shot {
  id: string; period: number; minute: number; second: number; home: boolean; team: string;
  playerId: string; player: string; x: number; y: number; endX: number | null; endY: number | null;
  xg: number | null; outcome: string; type: string; bodyPart: string; technique: string;
  goal: boolean; disallowed: boolean; shootout: boolean; freeze: FreezeActor[];
}

export interface PassNetwork {
  nodes: { id: string; name: string; x: number; y: number; touches: number }[];
  edges: { a: string; b: string; passes: number }[];
  untilMinute: number; note: string;
}

export interface TableRow {
  position: number; teamId: string; team: string; played: number; won: number; drawn: number;
  lost: number; goalsFor: number; goalsAgainst: number; goalDifference: number; points: number;
}

export interface Table {
  group: string; ruleId: string; explanation: string; note: string;
  unresolved: string[][]; rows: TableRow[];
}

export interface Collection { id: string; title: string; blurb: string; matches: MatchCard[] }

export interface Home {
  archive: { events: number; matches: number; players: number; competitions: number; seasons: number; from: string; to: string };
  live: MatchCard[];
  latest: MatchCard[];
  collections: Collection[];
  competitions: Omit<Competition, "seasons">[];
  tags: string[];
}

export interface SearchResult { kind: "competition" | "team" | "player"; id: string; name: string; subtitle: string }

export interface ReplayStatus {
  matchId: string; of: string; title: string; status: string; speed: number;
  sent: number; total: number; minute: number;
}

export interface Team {
  id: string; name: string; matches: number; won: number; drawn: number; lost: number;
  goalsFor: number; goalsAgainst: number; xgFor: number; xgAgainst: number;
  competitions: string[]; first: string; last: string;
}

export interface Player {
  id: string; name: string; teams: string[]; matches: number; goals: number; xg: number;
  assists: number; position: string; first: string; last: string;
}

export interface PlayerSeason {
  competitionId: number; seasonId: number; competition: string; season: string; team: string;
  matches: number; goals: number; xg: number; shots: number; assists: number; keyPasses: number;
  passes: number; passAccuracy: number; first: string; last: string;
}

export interface LeaderboardRow { playerId: string; player: string; team: string | null; matches: number; value: number }

export interface ApiErrorBody { error: string; message: string; detail: Record<string, unknown> }

/** A real fixture from football-data.org - not an archived match, not a replay. */
export interface Fixture {
  id: string; source: string;
  competition: { id: string; name: string; code: string };
  kickoffUtc: string;
  status: "scheduled" | "live" | "half_time" | "finished" | "postponed" | "suspended" | "cancelled" | string;
  matchday: number | null; stage: string;
  home: CurrentTeam;
  away: CurrentTeam;
  score: [number | null, number | null];
  halfTime: [number | null, number | null];
}

export interface CurrentTeam { id: string; name: string; fullName?: string; code: string }

export interface Today {
  enabled: boolean; ok?: boolean; message?: string; matches: Fixture[];
  from?: string; to?: string; fetchedAt?: number; stale?: boolean; source?: string;
}

export interface CurrentCompetition {
  code: string; id: string; name: string; type: string; area: string;
  season: { start: string; end: string; matchday: number | null };
  hasTable: boolean; hasScorers: boolean;
}

export interface CurrentTableRow {
  position: number; team: CurrentTeam; played: number; won: number; drawn: number; lost: number;
  goalsFor: number; goalsAgainst: number; goalDifference: number; points: number; form: string | null;
}

export interface CurrentStandings {
  code: string; matchday: number | null; fetchedAt: number; stale: boolean;
  tables: { stage: string; group: string; rows: CurrentTableRow[] }[];
}

export interface CurrentScorers {
  code: string; fetchedAt: number; stale: boolean;
  rows: { player: string; nationality: string; team: CurrentTeam; played: number | null;
          goals: number; assists: number | null; penalties: number | null }[];
}

/** GET /api/features: what this deployment can do. */
export interface Features {
  realtime: boolean;
  replays: boolean;
  current: boolean;
  deployment: "full" | "free-tier";
}

export type Network = "bluesky" | "mastodon" | "reddit" | "x";

export interface SocialPost {
  id: string; network: Network; url: string;
  author: { name: string; handle: string; avatar: string; url: string };
  text: string; createdAt: string; ts: number; lang: string;
  metrics: { likes?: number; reposts?: number; replies?: number };
  media: { thumb: string; alt: string }[];
  topics: string[]; via: string;
}

export interface SocialSourceState { state: "on" | "off" | "needs_key" | "paid_off" | "error"; message: string; count: number | null; at?: number }

export interface SocialTopic {
  id: string; label: string; kind: "fixture" | "competition"; competition: string; posts: number;
  status?: string; kickoffUtc?: string; score?: [number | null, number | null];
  home?: CurrentTeam; away?: CurrentTeam;
}

export interface SocialOverview {
  sources: Record<Network, SocialSourceState>;
  topics: SocialTopic[];
  trends: { tag: string; posts: number }[];
  volume: ({ hoursAgo: number } & Record<Network, number>)[];
  total24h: number;
}
