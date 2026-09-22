import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import clsx from "clsx";
import type { Network, SocialOverview, SocialPost, SocialSourceState, SocialTopic } from "../lib/types";

/**
 * The social feed. Posts are public, always shown with their author and a
 * link to the original, and rendered as text - never as HTML. Networks are
 * named and marked in neutral chalk: green, amber and violet already mean
 * something on Onside.
 */

export const NETWORK_LABEL: Record<Network, string> = { bluesky: "Bluesky", mastodon: "Mastodon", reddit: "Reddit", x: "X" };

export function NetworkGlyph({ network, className = "" }: { network: Network; className?: string }) {
  const common = { width: 12, height: 12, viewBox: "0 0 24 24", className: clsx("shrink-0", className), "aria-hidden": true } as const;
  if (network === "bluesky") return <svg {...common} fill="currentColor"><path d="M5.2 3.6C8 5.7 11 10 12 12.2c1-2.2 4-6.5 6.8-8.6 2-1.5 5.2-2.6 5.2 1 0 .7-.4 6-.7 6.9-.9 3-4 3.8-6.9 3.3 5 .9 6.3 3.7 3.5 6.5-5.2 5.4-7.5-1.3-8-3-.1-.3-.1-.5-.1-.4 0-.1 0 .1-.1.4-.5 1.7-2.8 8.4-8 3-2.8-2.8-1.5-5.6 3.5-6.5-2.9.5-6-.3-6.9-3.3C.4 10.6 0 5.3 0 4.6c0-3.6 3.2-2.5 5.2-1z" /></svg>;
  if (network === "mastodon") return <svg {...common} fill="currentColor"><path d="M21.3 13.9c-.3 1.5-2.6 3.2-5.3 3.5-1.4.2-2.8.3-4.3.2-2.4-.1-4.3-.6-4.3-.6v.7c.3 2.4 2.4 2.6 4.4 2.6 2 .1 3.8-.5 3.8-.5l.1 1.8s-1.4.7-3.8.9c-1.4.1-3-.1-5-.6C2.6 20.9 1.9 16.7 1.8 12.4v-3.4c0-4.4 2.9-5.7 2.9-5.7C6.1 2.6 8.6 2.4 11.2 2.3h.1c2.6 0 5.1.3 6.5 1 0 0 2.9 1.3 2.9 5.7 0 0 0 3.2-.4 4.9zM18.3 8.6c0-1.1-.3-2-.8-2.6-.6-.7-1.4-1-2.4-1-1.1 0-2 .4-2.5 1.3l-.6 1-.5-1c-.6-.9-1.4-1.3-2.5-1.3-1 0-1.8.3-2.4 1-.6.7-.8 1.5-.8 2.6v5.3h2.1V8.8c0-1.1.5-1.6 1.4-1.6 1 0 1.5.6 1.5 1.9v2.8h2.1V9.1c0-1.3.5-1.9 1.5-1.9.9 0 1.4.6 1.4 1.6v5.1h2.1z" /></svg>;
  if (network === "reddit") return <svg {...common} fill="currentColor"><circle cx="12" cy="13" r="7" /><circle cx="18.5" cy="5.5" r="1.8" /><path d="M12 6 13.5 1.8 18 3" stroke="currentColor" strokeWidth="1.2" fill="none" /></svg>;
  return <svg {...common} fill="currentColor"><path d="M17.8 3h3.1l-6.8 7.7 8 10.3h-6.3l-4.9-6.4L5.3 21H2.2l7.3-8.3L1.8 3h6.4l4.4 5.9zm-1.1 16.2h1.7L7.4 4.7H5.6z" /></svg>;
}

export function ago(ts: number, now = Date.now()): string {
  const s = Math.max(0, Math.round(now / 1000 - ts));
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

const URL = /(https?:\/\/[^\s<>"']+)/g;

/** Text with its links made clickable - built from strings, never from HTML. */
export function Linkified({ text }: { text: string }) {
  const parts = text.split(URL);
  return (
    <>
      {parts.map((part, i) => i % 2 === 1
        ? <a key={i} href={part} target="_blank" rel="noopener noreferrer nofollow ugc" className="break-all text-home underline decoration-home/30 underline-offset-2 hover:decoration-home">
            {part.replace(/^https?:\/\//, "").slice(0, 48)}{part.replace(/^https?:\/\//, "").length > 48 ? "…" : ""}
          </a>
        : <Fragment key={i}>{part}</Fragment>)}
    </>
  );
}

function Avatar({ post }: { post: SocialPost }) {
  const [broken, setBroken] = useState(false);
  const initial = (post.author.name || post.author.handle).replace(/^[@u/]+/, "").slice(0, 1).toUpperCase();
  if (!post.author.avatar || broken) {
    return <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-deck2 font-bold text-mute" aria-hidden>{initial}</span>;
  }
  return <img src={post.author.avatar} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)}
    className="h-9 w-9 shrink-0 rounded-full bg-deck2 object-cover" />;
}

export function PostCard({ post, topics }: { post: SocialPost; topics?: Map<string, SocialTopic> }) {
  const labels = post.topics.map((t) => topics?.get(t)).filter((t): t is SocialTopic => !!t && t.kind === "fixture");
  return (
    <article className="border-b border-rule/60 px-4 py-3.5 last:border-0">
      <header className="flex items-start gap-3">
        <Avatar post={post} />
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-baseline gap-x-2 text-[13.5px]">
            <a href={post.author.url} target="_blank" rel="noopener noreferrer nofollow" className="truncate font-bold hover:underline">{post.author.name}</a>
            <span className="truncate text-[12px] text-dim">{post.author.handle}</span>
          </p>
          <p className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-dim">
            <NetworkGlyph network={post.network} /> {NETWORK_LABEL[post.network]} · <time dateTime={post.createdAt} title={new Date(post.ts * 1000).toLocaleString()}>{ago(post.ts)}</time>
            {post.lang && <span className="uppercase">· {post.lang}</span>}
          </p>
        </div>
      </header>
      <p className="mt-2 whitespace-pre-line break-words text-[14px] leading-relaxed text-[#E1EBE4]"><Linkified text={post.text} /></p>
      {post.media.length > 0 && (
        <div className={clsx("mt-2.5 grid gap-1.5", post.media.length > 1 ? "grid-cols-2" : "grid-cols-1")}>
          {post.media.slice(0, 2).map((m) => (
            <img key={m.thumb} src={m.thumb} alt={m.alt || "Image attached to the post"} loading="lazy" referrerPolicy="no-referrer"
              className="max-h-72 w-full rounded-xl border border-rule bg-deck2 object-cover" />
          ))}
        </div>
      )}
      <footer className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px] text-dim">
        {labels.map((t) => <Link key={t.id} to={`/buzz?topic=${t.id}`} className="chip py-0.5 hover:text-chalk">{t.label}</Link>)}
        <span className="num" title="Likes">♥ {post.metrics.likes ?? 0}</span>
        <span className="num" title="Reposts">⟲ {post.metrics.reposts ?? 0}</span>
        <span className="num" title="Replies">💬 {post.metrics.replies ?? 0}</span>
        <a href={post.url} target="_blank" rel="noopener noreferrer nofollow" className="ml-auto font-bold text-mute hover:text-chalk">
          View on {NETWORK_LABEL[post.network]} ↗
        </a>
      </footer>
    </article>
  );
}

const STATE_TEXT: Record<SocialSourceState["state"], [string, string]> = {
  on: ["Connected", "text-grass"],
  off: ["Starting", "text-dim"],
  needs_key: ["Needs a key", "text-mute"],
  paid_off: ["Off - paid API", "text-mute"],
  error: ["Having trouble", "text-away"],
};

export function SourceList({ sources }: { sources: SocialOverview["sources"] }) {
  return (
    <ul className="divide-y divide-rule/60">
      {(Object.keys(NETWORK_LABEL) as Network[]).map((n) => {
        const s = sources[n];
        const [label, colour] = STATE_TEXT[s?.state ?? "off"];
        return (
          <li key={n} className="px-4 py-2.5">
            <p className="flex items-center gap-2 text-[13px] font-bold">
              <NetworkGlyph network={n} />{NETWORK_LABEL[n]}
              <span className={clsx("ml-auto font-mono text-[10.5px] uppercase tracking-wider", colour)}>{label}</span>
            </p>
            <p className="mt-0.5 text-[11.5px] leading-snug text-dim">{s?.message}{s?.state === "on" && s.count !== null ? ` Last run: ${s.count} new.` : ""}</p>
          </li>
        );
      })}
    </ul>
  );
}

/** Posts per hour, last twelve hours, as simple bars - one colour, since
 *  every colour on Onside already means something. */
export function VolumeBars({ volume }: { volume: SocialOverview["volume"] }) {
  const totals = volume.map((v) => (Object.keys(NETWORK_LABEL) as Network[]).reduce((s, n) => s + (v[n] ?? 0), 0));
  const max = Math.max(1, ...totals);
  return (
    <div className="px-4 pb-3 pt-2">
      <div className="flex h-24 items-end gap-1" role="img" aria-label={`Posts per hour over the last twelve hours, peaking at ${max}`}>
        {volume.map((v, i) => (
          <div key={v.hoursAgo} className="group relative flex-1">
            <div className="rounded-t bg-grass/70 transition-colors group-hover:bg-grass" style={{ height: `${Math.max(2, (totals[i] / max) * 96)}px` }} />
            <span className="pointer-events-none absolute -top-6 left-1/2 hidden -translate-x-1/2 whitespace-nowrap rounded bg-night px-1.5 py-0.5 font-mono text-[10px] text-chalk group-hover:block">{totals[i]}</span>
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10px] text-dim"><span>12h ago</span><span>now</span></div>
    </div>
  );
}
