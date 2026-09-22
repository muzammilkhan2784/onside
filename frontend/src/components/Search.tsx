import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { SearchResult } from "../lib/types";

const KIND_PATH: Record<SearchResult["kind"], string> = { competition: "/competitions", team: "/team", player: "/player" };

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

/** Command palette. Ctrl/Cmd+K or "/" opens it from anywhere. */
export default function Search() {
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const nav = useNavigate();
  const q = useDebounced(term.trim(), 150);
  const { data = [], isFetching } = useQuery({
    queryKey: ["search", q], queryFn: () => api.search(q), enabled: q.length >= 2, staleTime: 300_000,
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest("input, textarea");
      if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing)) {
        e.preventDefault(); setOpen(true);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => { if (open) { setTimeout(() => input.current?.focus(), 0); setActive(0); } }, [open]);
  useEffect(() => setActive(0), [q]);

  const go = (r: SearchResult) => { nav(`${KIND_PATH[r.kind]}/${r.id}`); setOpen(false); setTerm(""); };

  return (
    <>
      <button onClick={() => setOpen(true)}
        className="flex min-w-0 items-center gap-2 rounded-full border border-rule bg-deck px-3 py-1.5 text-[13px] text-dim transition hover:border-mute sm:w-56">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
        <span className="hidden truncate sm:inline">Search teams, players…</span>
        <kbd className="ml-auto hidden rounded border border-rule px-1.5 font-mono text-[10px] sm:inline">⌘K</kbd>
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-night/80 px-4 pt-[12vh] backdrop-blur-sm"
          onClick={() => setOpen(false)} role="dialog" aria-modal="true" aria-label="Search">
          <div className="panel w-full max-w-xl overflow-hidden shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <input ref={input} id="search-input" value={term} onChange={(e) => setTerm(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, data.length - 1)); }
                if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
                if (e.key === "Enter" && data[active]) go(data[active]);
              }}
              placeholder="Messi, Arsenal, World Cup…" autoComplete="off"
              className="w-full border-b border-rule bg-transparent px-5 py-4 text-[16px] text-chalk outline-none placeholder:text-dim" />
            <ul className="max-h-[50vh] overflow-y-auto py-1" role="listbox">
              {q.length < 2 && <li className="px-5 py-4 text-[13px] text-dim">Type at least two letters. Every competition, team and player in the archive is searchable.</li>}
              {q.length >= 2 && !isFetching && data.length === 0 && (
                <li className="px-5 py-4 text-[13px] text-dim">Nothing matches “{q}”. The archive covers the competitions StatsBomb has published, so some clubs and players aren't in it.</li>
              )}
              {data.map((r, i) => (
                <li key={`${r.kind}-${r.id}`} role="option" aria-selected={i === active}>
                  <button onMouseEnter={() => setActive(i)} onClick={() => go(r)}
                    className={`flex w-full items-center gap-3 px-5 py-2.5 text-left ${i === active ? "bg-deck2" : ""}`}>
                    <span className="w-20 shrink-0 font-mono text-[10px] uppercase tracking-wider text-dim">{r.kind}</span>
                    <span className="truncate font-bold">{r.name}</span>
                    <span className="ml-auto truncate text-[12px] text-dim">{r.subtitle}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </>
  );
}
