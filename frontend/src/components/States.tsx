import type { ReactNode } from "react";
import { ApiError } from "../lib/api";

/** Nothing is ever a blank screen: loading, empty and failed states all say,
 *  in plain English, what would be here and what to do next. */

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-deck2/70 ${className}`} aria-hidden />;
}

export function PageSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-label="Loading">
      <Skeleton className="h-10 w-1/3" />
      <Skeleton className="h-48" />
      <div className="grid gap-4 md:grid-cols-3">
        <Skeleton className="h-40" /><Skeleton className="h-40" /><Skeleton className="h-40" />
      </div>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="max-w-prose py-6 text-[13.5px] text-mute">
      <p className="mb-1 font-bold text-chalk">{title}</p>
      {children}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof ApiError
    ? error.message
    : "Something unexpected stopped this section from loading. Reloading the page usually fixes it.";
  const notFound = error instanceof ApiError && error.status === 404;
  return (
    <div className="panel p-5" role="alert">
      <p className="eyebrow mb-1">{notFound ? "Not in the archive" : "Couldn't load this"}</p>
      <p className="max-w-prose text-[14px] text-chalk">{message}</p>
      {retry && !notFound && <button className="btn mt-3" onClick={retry}>Try again</button>}
    </div>
  );
}
