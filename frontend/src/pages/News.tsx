import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import clsx from "clsx";
import { api } from "../lib/api";
import { TAG_LABEL } from "../lib/format";
import { StoryCard } from "../components/MatchCard";
import { Empty, ErrorState, PageSkeleton } from "../components/States";

const TAGS = ["turnaround", "penalties", "goal-fest", "smash-and-grab", "knockout", "stalemate"];

function CollectionView({ id }: { id: string }) {
  const { data, error, isLoading } = useQuery({ queryKey: ["collection", id], queryFn: () => api.collection(id) });
  if (isLoading) return <PageSkeleton />;
  if (error || !data) return <ErrorState error={error} />;
  return (
    <div className="space-y-4">
      <div>
        <Link to="/news" className="text-[13px] text-mute hover:text-chalk">← All stories</Link>
        <h1 className="mt-2 font-display text-4xl uppercase">{data.title}</h1>
        <p className="text-mute">{data.blurb}</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{data.matches.map((m) => <StoryCard key={m.id} card={m} />)}</div>
    </div>
  );
}

export default function News() {
  const [params, setParams] = useSearchParams();
  const tag = params.get("tag") ?? undefined;
  const collection = params.get("collection");
  const feed = useInfiniteQuery({
    queryKey: ["feed", tag],
    queryFn: ({ pageParam }) => api.feed({ tag, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next,
    enabled: !collection,
  });
  if (collection) return <CollectionView id={collection} />;

  const items = feed.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <div className="space-y-5">
      <div>
        <h1 className="font-display text-4xl uppercase sm:text-5xl">Stories</h1>
        <p className="max-w-2xl text-mute">One for every match in the archive. Each headline and standfirst is generated from the match's own win-probability swings - no wire copy, no language model.</p>
      </div>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter stories">
        <button onClick={() => setParams({})} aria-pressed={!tag} className={clsx("chip", !tag && "border-chalk text-chalk")}>Everything</button>
        {TAGS.map((t) => (
          <button key={t} onClick={() => setParams({ tag: t })} aria-pressed={tag === t}
            className={clsx("chip", tag === t && "border-chalk text-chalk")}>{TAG_LABEL[t]}</button>
        ))}
      </div>
      {feed.isLoading ? <PageSkeleton /> : feed.error ? <ErrorState error={feed.error} retry={feed.refetch} /> : items.length === 0 ? (
        <Empty title="No stories with that tag yet.">Pick another filter - tags are assigned from each match's numbers, so some are rare.</Empty>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{items.map((m) => <StoryCard key={m.id} card={m} />)}</div>
          {feed.hasNextPage && (
            <button className="btn mx-auto flex" onClick={() => feed.fetchNextPage()} disabled={feed.isFetchingNextPage}>
              {feed.isFetchingNextPage ? "Loading…" : "Older stories"}
            </button>
          )}
        </>
      )}
    </div>
  );
}
