import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import type { Features } from "../lib/types";

/** What an API from before /api/features could do: everything. */
const FULL: Features = { realtime: true, replays: true, current: true, deployment: "full" };

/** What this deployment can do, asked once per visit. The free-tier AWS
 *  deployment has no replays and no WebSockets, and the site hides both
 *  rather than offering buttons that fail. Undefined until the answer is in:
 *  anything that opens a socket waits for a definite yes. */
export function useFeatures(): Features | undefined {
  const { data } = useQuery({
    queryKey: ["features"],
    queryFn: () => api.features().catch((e: unknown) => {
      if (e instanceof ApiError && e.status === 404) return FULL;
      throw e;
    }),
    staleTime: Infinity,
    gcTime: Infinity,
    retry: 2,
  });
  return data;
}
