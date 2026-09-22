import { Link } from "react-router-dom";
import clsx from "clsx";
import type { MatchState, Report, Table, TeamStats, TimelineItem } from "../lib/types";
import { num, pct } from "../lib/format";
import { Crest } from "./Football";

// ---------------------------------------------------------------------------
// Stats with plain-English glosses
// ---------------------------------------------------------------------------

type StatKey = keyof TeamStats;
const STAT_ROWS: { key: StatKey; label: string; gloss?: string; fmt: (v: number) => string; lowerIsBetter?: boolean }[] = [
  { key: "xg", label: "Expected goals", gloss: "xg", fmt: (v) => num(v, 2) },
  { key: "shots", label: "Shots", fmt: (v) => String(v) },
  { key: "shotsOnTarget", label: "On target", gloss: "shots_on_target", fmt: (v) => String(v) },
  { key: "bigChances", label: "Big chances", gloss: "big_chances", fmt: (v) => String(v) },
  { key: "possession", label: "Possession", gloss: "possession", fmt: (v) => pct(v) },
  { key: "fieldTilt", label: "Field tilt", gloss: "field_tilt", fmt: (v) => pct(v) },
  { key: "passAccuracy", label: "Pass accuracy", gloss: "pass_accuracy", fmt: (v) => pct(v) },
  { key: "progressivePasses", label: "Progressive passes", gloss: "progressive_passes", fmt: (v) => String(v) },
  { key: "ppda", label: "PPDA (pressing)", gloss: "ppda", fmt: (v) => num(v, 1), lowerIsBetter: true },
  { key: "corners", label: "Corners", fmt: (v) => String(v) },
  { key: "fouls", label: "Fouls", fmt: (v) => String(v), lowerIsBetter: true },
];

export function StatBars({ state }: { state: MatchState }) {
  const { home, away } = state.stats;
  return (
    <dl className="space-y-3.5">
      {STAT_ROWS.map((r) => {
        const h = home[r.key] as number | null, a = away[r.key] as number | null;
        if (h === null || a === null) {
          return (
            <div key={r.key}>
              <dt className="mb-1 text-center text-[12px] text-mute">{r.label}</dt>
              <dd className="text-center text-[12px] text-dim">Not enough defensive actions high up the pitch to measure.</dd>
            </div>
          );
        }
        const total = (h || 0) + (a || 0) || 1;
        const hBetter = r.lowerIsBetter ? h < a : h > a;
        const aBetter = r.lowerIsBetter ? a < h : a > h;
        return (
          <div key={r.key} className="group">
            <div className="mb-1 grid grid-cols-[4rem_1fr_4rem] items-baseline text-[13px]">
              <dd className={clsx("num font-mono", hBetter ? "font-bold text-chalk" : "text-mute")}>{r.fmt(h)}</dd>
              <dt className="text-center text-[12px] text-mute">
                {r.label}
                {r.gloss && state.glossary[r.gloss] && (
                  <span className="ml-1 cursor-help text-dim" title={state.glossary[r.gloss]} aria-label={state.glossary[r.gloss]}>ⓘ</span>
                )}
              </dt>
              <dd className={clsx("num text-right font-mono", aBetter ? "font-bold text-chalk" : "text-mute")}>{r.fmt(a)}</dd>
            </div>
            <div className="flex h-1.5 gap-1 overflow-hidden rounded-full">
              <div className="rounded-full bg-home" style={{ width: `${(h / total) * 100}%`, opacity: hBetter ? 1 : 0.45 }} />
              <div className="rounded-full bg-away" style={{ width: `${(a / total) * 100}%`, opacity: aBetter ? 1 : 0.45 }} />
            </div>
            {r.gloss && state.glossary[r.gloss] && (
              <p className="mt-1 hidden text-[11.5px] text-dim group-hover:block group-focus-within:block">{state.glossary[r.gloss]}</p>
            )}
          </div>
        );
      })}
    </dl>
  );
}

// ---------------------------------------------------------------------------
// Timeline - corrections inline, the original event struck through
// ---------------------------------------------------------------------------

const KIND_LABEL: Record<TimelineItem["kind"], string> = {
  goal: "Goal", own_goal: "Own goal", card: "Card", sub: "Substitution", big_chance: "Big chance",
  penalty_miss: "Penalty missed", shootout: "Shootout", correction: "Correction",
};

export function Timeline({ state }: { state: MatchState }) {
  const items = state.timeline.filter((t) => t.kind !== "shootout");
  const shootout = state.timeline.filter((t) => t.kind === "shootout");
  if (!items.length) {
    return <p className="p-4 text-[13px] text-mute">Nothing notable yet. The timeline fills in as the match plays - every entry is appended, and nothing is ever removed.</p>;
  }
  return (
    <ol className="divide-y divide-rule/50">
      {items.map((t) => {
        const side = t.home === null ? "" : t.home ? state.home.name : state.away.name;
        const isGoal = t.kind === "goal" || t.kind === "own_goal";
        return (
          <li key={`${t.kind}-${t.eventId}`}
            className={clsx("grid grid-cols-[3rem_1fr] gap-3 border-l-[3px] px-4 py-2.5",
              t.kind === "correction" ? "border-signal bg-signal/[.07]"
                : isGoal ? (t.home ? "border-home bg-home/[.05]" : "border-away bg-away/[.05]")
                : t.kind === "card" ? (t.detail === "Yellow Card" ? "border-[#C9A227]" : "border-away") : "border-transparent")}>
            <span className="pt-0.5 font-mono text-[12px] text-dim num">{t.minute}'</span>
            <div className="min-w-0">
              <p className={clsx("text-[13.5px] font-bold", t.disallowed && "text-mute line-through decoration-signal decoration-2")}>
                {t.kind === "correction" ? (
                  <>
                    {t.correctionKind === "disallow" ? "Goal disallowed" : t.correctionKind === "reinstate" ? "Goal reinstated" : t.correctionKind === "reassign" ? "Goal reassigned" : "Detail corrected"}
                    <span className="ml-2 rounded bg-signal px-1.5 py-0.5 font-mono text-[9.5px] uppercase tracking-wider text-[#241900]">{t.authority}</span>
                    {t.synthesised && <span className="ml-1.5 rounded border border-rule px-1.5 py-0.5 font-mono text-[9.5px] uppercase tracking-wider text-dim" title="StatsBomb open data has no VAR decisions; Onside synthesised this one for the replay.">synthesised</span>}
                  </>
                ) : t.kind === "sub" ? <>{t.detail} <span className="font-normal text-dim">on for</span> {t.player}</>
                  : t.player}
              </p>
              <p className="text-[12.5px] text-mute">
                {t.kind === "correction" ? t.detail
                  : t.kind === "card" ? `${t.detail} — ${side}`
                  : `${KIND_LABEL[t.kind]}${t.kind === "goal" && t.detail === "Penalty" ? " (penalty)" : ""} — ${side}${t.xg != null ? ` · xG ${t.xg.toFixed(2)}` : ""}`}
                {t.disallowed && <span className="text-signal"> · ruled out at {t.correctedAt}': {t.correctionReason}</span>}
              </p>
            </div>
          </li>
        );
      })}
      {shootout.length > 0 && (
        <li className="px-4 py-3">
          <p className="eyebrow mb-2">Penalty shootout</p>
          <div className="flex flex-wrap gap-1.5">
            {shootout.map((t) => (
              <span key={t.eventId} title={`${t.player} - ${t.detail}`}
                className={clsx("grid h-7 w-7 place-items-center rounded-full border text-[11px] font-bold",
                  t.detail === "scored" ? (t.home ? "border-home bg-home/20" : "border-away bg-away/20") : "border-rule text-dim line-through")}>
                {t.player.split(" ").slice(-1)[0][0]}
              </span>
            ))}
          </div>
        </li>
      )}
    </ol>
  );
}

// ---------------------------------------------------------------------------
// The generated report
// ---------------------------------------------------------------------------

export function ReportView({ report, corrected, synthesised }: { report: Report; corrected: boolean; synthesised: boolean }) {
  return (
    <article className="space-y-4">
      <h3 className="font-display text-xl uppercase leading-tight tracking-wide [text-wrap:balance]">{report.headline}</h3>
      <p className="max-w-prose text-[15px] leading-relaxed text-[#CFE0D4]">{report.lede}</p>
      <ol className="space-y-2.5">
        {report.lines.map((line, i) => {
          const m = /^(\d+)' - (.*)$/.exec(line);
          return (
            <li key={i} className="grid grid-cols-[2.8rem_1fr] gap-3 text-[14px] leading-relaxed">
              <span className="pt-0.5 font-mono text-[12px] text-signal num">{m ? `${m[1]}'` : ""}</span>
              <span>{m ? m[2] : line}</span>
            </li>
          );
        })}
      </ol>
      {report.closing && <p className="border-t border-rule pt-3 text-[14px] text-[#CFE0D4]">{report.closing}</p>}
      {report.notes.map((n) => <p key={n} className="border-l-2 border-rule pl-3 text-[12px] text-dim">{n}</p>)}
      {corrected && !report.notes.length && <p className="border-l-2 border-signal pl-3 text-[12px] text-dim">Regenerated after a correction.{synthesised && " The correction was synthesised for this replay."}</p>}
      <p className="text-[11.5px] text-dim">Written by rules, not a language model: moments are ranked by how far they moved the win probability, then templated. Every sentence is reproducible.</p>
    </article>
  );
}

// ---------------------------------------------------------------------------
// League table
// ---------------------------------------------------------------------------

export function LeagueTable({ table }: { table: Table }) {
  return (
    <div className="panel overflow-hidden">
      <div className="panel-head">
        <h3 className="h-section">{table.group}</h3>
        <span className="text-[11.5px] text-dim">{table.explanation}</span>
      </div>
      <div className="scroll-x">
        <table className="w-full min-w-[34rem] text-[13px]">
          <thead className="text-left font-mono text-[10.5px] uppercase tracking-wider text-dim">
            <tr>{["#", "Team", "P", "W", "D", "L", "GF", "GA", "GD", "Pts"].map((h, i) => (
              <th key={h} scope="col" className={clsx("px-3 py-2 font-normal", i > 1 && "text-right")}>{h}</th>))}</tr>
          </thead>
          <tbody className="num">
            {table.rows.map((r) => (
              <tr key={r.teamId} className="border-t border-rule/60 hover:bg-deck2/50">
                <td className="px-3 py-2 font-mono text-dim">{r.position}</td>
                <td className="px-3 py-2 font-bold"><Link className="flex items-center gap-2 hover:text-grass" to={`/team/${r.teamId}`}><Crest name={r.team} size={18} />{r.team}</Link></td>
                {[r.played, r.won, r.drawn, r.lost, r.goalsFor, r.goalsAgainst].map((v, i) => <td key={i} className="px-3 py-2 text-right text-mute">{v}</td>)}
                <td className="px-3 py-2 text-right">{r.goalDifference > 0 ? `+${r.goalDifference}` : r.goalDifference}</td>
                <td className="px-3 py-2 text-right font-display text-[15px]">{r.points}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(table.note || table.unresolved.length > 0) && (
        <p className="border-t border-rule px-4 py-2 text-[11.5px] text-dim">
          {table.note}{table.unresolved.length > 0 && " Some teams are still level after every tie-break rule; they are listed alphabetically and would need a play-off or drawing of lots."}
        </p>
      )}
    </div>
  );
}
