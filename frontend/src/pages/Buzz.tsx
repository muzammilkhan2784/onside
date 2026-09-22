import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "../lib/api";
import type { Network, SocialTopic } from "../lib/types";
import { NETWORK_LABEL, NetworkGlyph, PostCard, SourceList, VolumeBars } from "../components/Social";
import { Crest, LiveBadge } from "../components/Football";
import { kickoffTime } from "../components/Current";
import { ErrorState, Skeleton } from "../components/States";

function TopicButton({ t, active, onPick }: { t: SocialTopic | null; active: boolean; onPick: () => void }) {
  return (
    <button onClick={onPick} aria-pressed={active}
      className={clsx("flex w-full items-center gap-2 px-4 py-2 text-left text-[13px] transition-colors",
        active ? "bg-grass/10 text-chalk" : "text-mute hover:bg-deck2/60 hover:text-chalk")}>
      {t?.kind === "fixture" && t.home && t.away ? (
        <>
          <span className="flex -space-x-1"><Crest name={t.home.name} code={t.home.code} size={16} /><Crest name={t.away.name} code={t.away.code} size={16} /></span>
          <span className="min-w-0 flex-1 truncate font-semibold">{t.label}</span>
          {t.status === "live" || t.status === "half_time"
            ? <span className="font-mono text-[10px] font-bold text-live">LIVE</span>
            : t.status === "finished" && t.score
              ? <span className="font-mono text-[10.5px] num">{t.score[0]}–{t.score[1]}</span>
              : t.kickoffUtc ? <span className="font-mono text-[10.5px] text-dim num">{kickoffTime(t.kickoffUtc)}</span> : null}
        </>
      ) : <span className="min-w-0 flex-1 truncate font-semibold">{t ? t.label : "All football"}</span>}
      {t && <span className="font-mono text-[10.5px] text-dim num">{t.posts}</span>}
    </button>
  );
}

/** The social dashboard: what people are posting about the football that is
 *  being played now. */
export default function Buzz() {
  const [params, setParams] = useSearchParams();
  const topic = params.get("topic") || "all";
  const network = (params.get("network") || "") as Network | "";
  const english = params.get("lang") !== "all"; // English by default; posts with no language tag still show
  const set = (k: string, v: string) => { const n = new URLSearchParams(params); if (v) n.set(k, v); else n.delete(k); setParams(n, { replace: true }); };

  const qc = useQueryClient();
  const overview = useQuery({ queryKey: ["social-overview"], queryFn: api.socialOverview, refetchInterval: 60_000 });
  const key = ["social", topic, network, english] as const;
  const feed = useInfiniteQuery({
    queryKey: key,
    queryFn: ({ pageParam }) => api.social({ topic, network, lang: english ? "en" : undefined, before: pageParam, limit: 25 }),
    initialPageParam: null as number | null,
    getNextPageParam: (p) => p.next,
  });
  // New posts: check quietly and offer them, rather than shifting the list
  // under someone's thumb while they read.
  const newest = feed.data?.pages[0]?.items[0]?.ts ?? 0;
  const peek = useQuery({
    queryKey: ["social-peek", ...key],
    queryFn: () => api.social({ topic, network, lang: english ? "en" : undefined, limit: 25 }),
    refetchInterval: 30_000,
    enabled: !!feed.data,
  });
  const waiting = (peek.data?.items ?? []).filter((p) => p.ts > newest).length;
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => { const f = () => setScrolled(window.scrollY > 400); window.addEventListener("scroll", f, { passive: true }); return () => window.removeEventListener("scroll", f); }, []);
  const showNew = () => { qc.resetQueries({ queryKey: key }); window.scrollTo({ top: 0, behavior: "smooth" }); };

  const topics = useMemo(() => new Map((overview.data?.topics ?? []).map((t) => [t.id, t])), [overview.data]);
  const fixtures = (overview.data?.topics ?? []).filter((t) => t.kind === "fixture");
  const comps = (overview.data?.topics ?? []).filter((t) => t.kind === "competition");
  const current = topics.get(topic);
  const posts = feed.data?.pages.flatMap((p) => p.items) ?? [];
  const sourcesOn = overview.data ? Object.values(overview.data.sources).filter((s) => s.state === "on").length : 0;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl uppercase sm:text-5xl">Buzz</h1>
          <p className="mt-1 max-w-2xl text-mute">
            What people are posting about the football being played now - public posts from Bluesky and Mastodon, each
            with its author and a link to the original. Onside keeps them for three days and shows them as posted.
          </p>
        </div>
        <dl className="flex gap-2">
          {[["Posts, last 24h", overview.data?.total24h ?? "…"], ["Sources on", overview.data ? `${sourcesOn} of 4` : "…"],
            ["Matches followed", fixtures.length || "…"]].map(([k, v]) => (
            <div key={k} className="rounded-xl border border-rule bg-deck px-3 py-2">
              <dt className="eyebrow">{k}</dt><dd className="font-display text-2xl num">{v}</dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="grid gap-4 lg:grid-cols-[16rem_minmax(0,1fr)_18rem]">
        {/* On a phone the topics are one swipeable row, so the posts come first. */}
        <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 scroll-x lg:hidden">
          {[null, ...fixtures, ...comps].map((t) => (
            <button key={t?.id ?? "all"} onClick={() => set("topic", t?.id ?? "")} aria-pressed={topic === (t?.id ?? "all")}
              className={clsx("chip shrink-0 normal-case tracking-normal", topic === (t?.id ?? "all") && "border-grass/60 text-chalk")}>
              {t ? t.label : "All football"}{t ? <span className="text-dim num">{t.posts}</span> : null}
            </button>
          ))}
        </div>
        <aside className="hidden space-y-4 lg:sticky lg:top-20 lg:block lg:self-start">
          <section className="panel overflow-hidden">
            <div className="panel-head"><h2 className="h-section">Topics</h2></div>
            <TopicButton t={null} active={topic === "all"} onPick={() => set("topic", "")} />
            {fixtures.length > 0 && <p className="eyebrow px-4 pb-1 pt-3">Matches</p>}
            {fixtures.map((t) => <TopicButton key={t.id} t={t} active={topic === t.id} onPick={() => set("topic", t.id)} />)}
            {comps.length > 0 && <p className="eyebrow px-4 pb-1 pt-3">Competitions</p>}
            {comps.map((t) => <TopicButton key={t.id} t={t} active={topic === t.id} onPick={() => set("topic", t.id)} />)}
            {!overview.data && <Skeleton className="m-4 h-40" />}
          </section>
        </aside>

        <section className="panel min-w-0 overflow-hidden">
          <div className="panel-head">
            <h2 className="h-section truncate">{current ? current.label : "All football"}</h2>
            {current?.kind === "fixture" && (current.status === "live" || current.status === "half_time") && <LiveBadge />}
          </div>
          <div className="flex flex-wrap items-center gap-1.5 border-b border-rule px-4 py-2.5">
            {(["", "bluesky", "mastodon", "reddit", "x"] as const).map((n) => (
              <button key={n || "all"} onClick={() => set("network", n)} aria-pressed={network === n}
                className={clsx("chip gap-1.5", network === n ? "border-grass/60 text-chalk" : "hover:text-chalk")}>
                {n && <NetworkGlyph network={n} />}{n ? NETWORK_LABEL[n] : "All networks"}
              </button>
            ))}
            <label className="ml-auto flex items-center gap-2 text-[12.5px] text-mute">
              <input type="checkbox" checked={english} onChange={(e) => set("lang", e.target.checked ? "" : "all")} className="accent-grass" />
              English only
            </label>
          </div>
          {waiting > 0 && (
            <button onClick={showNew} className={clsx("text-[13px] font-bold",
              scrolled
                ? "fixed left-1/2 top-20 z-30 -translate-x-1/2 rounded-full border border-grass/50 bg-night px-4 py-2 text-grass shadow-lg shadow-black/40"
                : "w-full border-b border-grass/30 bg-grass/10 py-2 text-grass hover:bg-grass/15")}>
              {waiting >= 25 ? "25+" : waiting} new post{waiting === 1 ? "" : "s"} - show
            </button>
          )}
          {feed.isLoading ? <div className="space-y-3 p-4"><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /></div>
            : feed.error ? <div className="p-4"><ErrorState error={feed.error} retry={feed.refetch} /></div>
            : !posts.length ? (
              <div className="p-5 text-[13.5px] text-mute">
                <p className="font-bold text-chalk">No posts here yet.</p>
                <p className="mt-1">{topic !== "all"
                  ? "Nobody on the connected networks has posted about this yet - posts are collected every few minutes, and match chatter builds towards kick-off."
                  : "The social worker collects posts every few minutes. If this stays empty, check the sources panel."}</p>
              </div>
            ) : (
              <>
                {posts.map((p) => <PostCard key={p.id} post={p} topics={topics} />)}
                <div className="p-3 text-center">
                  {feed.hasNextPage
                    ? <button className="btn" onClick={() => feed.fetchNextPage()} disabled={feed.isFetchingNextPage}>{feed.isFetchingNextPage ? "Loading…" : "Older posts"}</button>
                    : <p className="text-[12px] text-dim">That is everything from the last three days.</p>}
                </div>
              </>
            )}
        </section>

        <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
          <section className="panel overflow-hidden">
            <div className="panel-head"><h2 className="h-section">Posts per hour</h2></div>
            {overview.data ? <VolumeBars volume={overview.data.volume} /> : <Skeleton className="m-4 h-24" />}
          </section>
          <section className="panel overflow-hidden">
            <div className="panel-head"><h2 className="h-section">Trending tags</h2><span className="text-[11px] text-dim">last 6h</span></div>
            <div className="flex flex-wrap gap-1.5 p-4">
              {overview.data?.trends.length ? overview.data.trends.map((t) => (
                <span key={t.tag} className="chip normal-case tracking-normal">#{t.tag} <b className="text-chalk num">{t.posts}</b></span>
              )) : <p className="text-[12.5px] text-dim">Tags appear once enough posts use them.</p>}
            </div>
          </section>
          <section className="panel overflow-hidden">
            <div className="panel-head"><h2 className="h-section">Sources</h2></div>
            {overview.data ? <SourceList sources={overview.data.sources} /> : <Skeleton className="m-4 h-32" />}
          </section>
        </aside>
      </div>
    </div>
  );
}
