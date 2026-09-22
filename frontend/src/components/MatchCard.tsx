import { Link } from "react-router-dom";
import clsx from "clsx";
import type { MatchCard as Card } from "../lib/types";
import { shortDate, TAG_LABEL } from "../lib/format";
import { CompetitionMark, Crest, FullTime, ReplayBadge } from "./Football";

function TeamLine({ name, goals, won, side }: { name: string; goals: number; won: boolean; side: "home" | "away" }) {
  return (
    <div className="flex items-center gap-2.5">
      <Crest name={name} size={22} />
      <span className={clsx("min-w-0 flex-1 truncate", won ? "font-extrabold text-chalk" : "font-semibold text-mute")}>{name}</span>
      <span className={clsx("w-6 text-right font-display text-[20px] leading-none num", won ? "text-chalk" : "text-mute")}
        aria-label={`${side} goals`}>{goals}</span>
    </div>
  );
}

/** A story card: the generated headline and standfirst under a result block. */
export function StoryCard({ card, feature = false }: { card: Card; feature?: boolean }) {
  const [h, a] = card.score;
  const pens = card.shootout;
  const homeWon = pens ? pens[0] > pens[1] : h > a;
  const awayWon = pens ? pens[1] > pens[0] : a > h;
  return (
    <Link to={`/match/${card.id}`}
      className={clsx("group panel flex flex-col overflow-hidden transition-colors hover:border-grass/50 hover:bg-deck2/40",
        feature && "md:col-span-2", card.live && "border-replay/40")}>
      <div className="flex items-center justify-between gap-2 border-b border-rule/70 bg-deck2/40 px-4 py-2">
        <span className="flex min-w-0 items-center gap-2">
          <CompetitionMark name={card.competition.name} size={18} />
          <span className="eyebrow truncate text-mute">{card.competition.name} · {card.stage || card.season.name}</span>
        </span>
        {card.live ? <ReplayBadge /> : <span className="eyebrow shrink-0">{shortDate(card.date)}</span>}
      </div>
      <div className="flex gap-4 px-4 pt-3">
        <div className="min-w-0 flex-1 space-y-1.5">
          <TeamLine name={card.home.name} goals={h} won={homeWon} side="home" />
          <TeamLine name={card.away.name} goals={a} won={awayWon} side="away" />
        </div>
        <div className="flex flex-col items-end justify-center gap-1 border-l border-rule/70 pl-3">
          {!card.live && <FullTime shootout={pens} />}
          {pens && <span className="font-mono text-[10.5px] text-mute num">{pens[0]}–{pens[1]}</span>}
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-2 px-4 pb-4 pt-3">
        <p className={clsx("font-bold leading-snug text-chalk group-hover:text-grass", feature ? "text-[17px]" : "text-[14.5px]")}>{card.headline}</p>
        <p className={clsx("text-[13px] leading-snug text-mute", feature ? "line-clamp-3" : "line-clamp-2")}>{card.standfirst}</p>
        <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-1">
          {card.tags.slice(0, 3).map((t) => <span key={t} className="chip py-0.5">{TAG_LABEL[t] ?? t}</span>)}
          {card.xg[0] !== null && (
            <span className="ml-auto font-mono text-[10.5px] text-dim num">xG {card.xg[0]?.toFixed(1)}–{card.xg[1]?.toFixed(1)}</span>
          )}
        </div>
      </div>
    </Link>
  );
}

/** A dense fixture row for lists of many matches, scores-app style. */
export function FixtureRow({ card, focusTeam, showDate = true }: { card: Card; focusTeam?: string; showDate?: boolean }) {
  const [h, a] = card.score;
  const pens = card.shootout;
  const homeWon = pens ? pens[0] > pens[1] : h > a;
  const awayWon = pens ? pens[1] > pens[0] : a > h;
  let result: "W" | "D" | "L" | null = null;
  if (focusTeam) {
    const home = card.home.id === focusTeam;
    const won = home ? homeWon : awayWon, lost = home ? awayWon : homeWon;
    result = won ? "W" : lost ? "L" : "D";
  }
  return (
    <Link to={`/match/${card.id}`}
      className="grid grid-cols-[3rem_1fr_auto_1fr_2rem] items-center gap-2 border-b border-rule/60 px-3 py-2.5 text-[13.5px] transition last:border-0 hover:bg-deck2/60 sm:grid-cols-[5.5rem_1fr_auto_1fr_3.5rem] sm:gap-3 sm:px-4">
      <span className="flex flex-col font-mono text-[10.5px] leading-tight text-dim num">
        {card.live ? <span className="text-replay">Replay</span> : <span className="font-bold text-mute">{pens ? "Pens" : "FT"}</span>}
        {showDate && <span className="hidden sm:block">{shortDate(card.date)}</span>}
      </span>
      <span className="flex min-w-0 items-center justify-end gap-2">
        <span className={clsx("truncate text-right", homeWon ? "font-extrabold" : "text-mute")}>{card.home.name}</span>
        <Crest name={card.home.name} size={18} />
      </span>
      <span className="min-w-[3.4rem] rounded-md bg-night/70 px-2 py-1 text-center font-display text-[15px] leading-none ring-1 ring-rule num">
        {h}–{a}
        {pens && <span className="block pt-0.5 font-mono text-[9px] text-mute">{pens[0]}–{pens[1]} p</span>}
      </span>
      <span className="flex min-w-0 items-center gap-2">
        <Crest name={card.away.name} size={18} />
        <span className={clsx("truncate", awayWon ? "font-extrabold" : "text-mute")}>{card.away.name}</span>
      </span>
      {result ? (
        <span className={clsx("grid h-6 w-6 place-items-center justify-self-end rounded-md font-mono text-[11px] font-bold",
          result === "W" && "bg-grass/20 text-grass", result === "D" && "bg-deck2 text-mute", result === "L" && "bg-away/15 text-away")}>
          {result}
        </span>
      ) : <span className="hidden justify-self-end truncate font-mono text-[10px] text-dim sm:block">
        {card.stage === "Regular Season" && card.matchWeek ? `MW${card.matchWeek}` : ""}</span>}
    </Link>
  );
}
