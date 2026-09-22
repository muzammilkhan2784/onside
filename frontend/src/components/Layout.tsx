import { useCallback, useState, type ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import Search from "./Search";
import { api } from "../lib/api";
import { useFeedSocket } from "../hooks/useLiveMatch";
import type { MatchCard } from "../lib/types";
import { Crest } from "./Football";

const NAV = [
  { to: "/", label: "Home", end: true },
  { to: "/matches", label: "Matches" },
  { to: "/buzz", label: "Buzz" },
  { to: "/news", label: "Stories" },
  { to: "/competitions", label: "Competitions" },
  { to: "/stats", label: "Stats" },
  { to: "/replays", label: "Replays" },
];

function Wordmark() {
  // A pitch seen from above, with the offside line drawn across it.
  return (
    <Link to="/" className="group flex items-center gap-2.5" aria-label="Onside home">
      <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden>
        <rect x="2" y="5" width="28" height="22" rx="3" fill="#123522" stroke="#2FCB74" strokeWidth="1.6" />
        <line x1="16" y1="5" x2="16" y2="27" stroke="#2FCB74" strokeWidth="1.2" />
        <circle cx="16" cy="16" r="3.6" fill="none" stroke="#2FCB74" strokeWidth="1.2" />
        <line x1="22.5" y1="3" x2="22.5" y2="29" stroke="#FFC53D" strokeWidth="1.8" strokeDasharray="2.2 1.6" className="transition group-hover:stroke-white" />
      </svg>
      <span className="font-display text-[26px] uppercase leading-none tracking-[0.03em]">On<span className="text-grass">side</span></span>
    </Link>
  );
}

/** The replay strip: archived matches replaying right now, updated over the
 *  feed socket. Hidden when nothing is replaying - it never shows a finished
 *  match as if it were still being played. */
function Ticker() {
  const qc = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ["live"], queryFn: api.live, refetchInterval: 30_000 });
  const [flash, setFlash] = useState<string | null>(null);
  const onScore = useCallback((card: unknown) => {
    const c = card as MatchCard;
    // Update a replay already in the strip in place; anything else means the
    // set of playing replays may have changed, so ask the API rather than
    // trusting a pushed card to still be playing.
    let known = false;
    qc.setQueryData<MatchCard[]>(["live"], (old = []) => old.map((m) => {
      if (m.id !== c.id) return m;
      known = true;
      return c;
    }));
    if (!known) qc.invalidateQueries({ queryKey: ["live"] });
    setFlash(c.id);
    setTimeout(() => setFlash(null), 1500);
  }, [qc]);
  useFeedSocket(onScore);
  if (!data.length) return null;
  return (
    <div className="border-b border-replay/20 bg-replay/[.06]">
      <div className="mx-auto flex max-w-7xl items-center gap-3 overflow-x-auto px-4 py-1.5 scroll-x">
        <span className="shrink-0 font-mono text-[10.5px] font-bold uppercase tracking-[0.1em] text-replay">Replaying now</span>
        {data.map((m) => (
          <Link key={m.id} to={`/match/${m.id}`}
            className={clsx("flex shrink-0 items-center gap-2 rounded-full px-3 py-1 text-[13px] transition hover:bg-deck2",
              flash === m.id && "bg-signal/15")}>
            <Crest name={m.home.name} size={14} />
            <span className="font-bold">{m.home.name}</span>
            <span className="font-display num text-[15px]">{m.score[0]}–{m.score[1]}</span>
            <span className="font-bold">{m.away.name}</span>
            <Crest name={m.away.name} size={14} />
            <span className="font-mono text-[10px] text-dim">played {m.date.slice(0, 4)}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const [menu, setMenu] = useState(false);
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 btn">Skip to content</a>
      <header className="sticky top-0 z-40 border-b border-rule bg-night/95" style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}>
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
          <Wordmark />
          <nav className="hidden items-center gap-1 md:flex" aria-label="Main">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end}
                className={({ isActive }) => clsx("rounded-full px-3 py-1.5 text-[13.5px] font-bold transition",
                  isActive ? "bg-grass/15 text-grass" : "text-mute hover:text-chalk")}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <Search />
            <button className="btn px-3 md:hidden" onClick={() => setMenu((m) => !m)} aria-expanded={menu} aria-label="Menu">☰</button>
          </div>
        </div>
        {menu && (
          <nav className="flex flex-wrap gap-1 border-t border-rule px-4 py-2 md:hidden" aria-label="Main">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end} onClick={() => setMenu(false)}
                className={({ isActive }) => clsx("rounded-full px-3 py-1.5 text-[13.5px] font-bold", isActive ? "bg-grass/15 text-grass" : "text-mute")}>
                {n.label}
              </NavLink>
            ))}
          </nav>
        )}
      </header>
      <Ticker />
      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>
      <footer className="border-t border-rule">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-6 text-[12px] text-dim">
          <p>Event data: <strong className="text-mute">StatsBomb Open Data</strong>, used under their free licence. Onside is an independent portfolio project, not affiliated with StatsBomb. Crests are generated, not club badges.</p>
          <p className="flex gap-4"><Link className="link" to="/about">How it works</Link><a className="link" href="/docs">API</a></p>
        </div>
      </footer>
    </div>
  );
}
