import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Competition } from "../lib/types";
import { ErrorState, PageSkeleton } from "../components/States";
import { CompetitionMark } from "../components/Football";

function Group({ title, comps }: { title: string; comps: Competition[] }) {
  if (!comps.length) return null;
  return (
    <section className="space-y-3">
      <h2 className="h-section">{title}</h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {comps.map((c) => (
          <Link key={c.id} to={`/competitions/${c.id}`} className="panel group p-4 transition hover:border-grass/50">
            <div className="flex items-start justify-between gap-3">
              <CompetitionMark name={c.name} size={36} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[16px] font-extrabold group-hover:text-grass">{c.name}</p>
                <p className="text-[12.5px] text-dim">{c.country}</p>
              </div>
              <span className="font-display text-2xl num text-mute">{c.matches}</span>
            </div>
            <p className="mt-3 truncate text-[12px] text-mute">
              {c.seasons.length} season{c.seasons.length === 1 ? "" : "s"} · {c.seasons[c.seasons.length - 1]?.name} to {c.seasons[0]?.name}
            </p>
          </Link>
        ))}
      </div>
    </section>
  );
}

export default function Competitions() {
  const { data, error, isLoading, refetch } = useQuery({ queryKey: ["competitions"], queryFn: api.competitions, staleTime: 600_000 });
  if (isLoading) return <PageSkeleton />;
  if (error || !data) return <ErrorState error={error} retry={refetch} />;
  const men = data.filter((c) => c.gender !== "female");
  const women = data.filter((c) => c.gender === "female");
  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-4xl uppercase sm:text-5xl">Competitions</h1>
        <p className="max-w-2xl text-mute">
          Everything in the StatsBomb open-data archive: {data.length} competitions and {data.reduce((a, c) => a + c.matches, 0).toLocaleString()} matches.
          Global live coverage needs a paid feed - Onside's adapter layer is ready for one; the archive is what's free.
        </p>
      </div>
      <Group title="International - men" comps={men.filter((c) => c.international)} />
      <Group title="Club - men" comps={men.filter((c) => !c.international)} />
      <Group title="International - women" comps={women.filter((c) => c.international)} />
      <Group title="Club - women" comps={women.filter((c) => !c.international)} />
    </div>
  );
}
