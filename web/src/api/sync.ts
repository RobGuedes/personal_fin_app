import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "./client";

export interface SyncStatus {
  running: boolean;
  step: string | null;
  started_at: string | null;
  finished_at: string | null;
  report: { warnings: string[]; errors: string[]; counts: unknown } | null;
  runs: { started_at: string; finished_at: string | null; items_synced: number | null; inserted: number | null; updated: number | null; deleted: number | null; error_count: number }[];
  items: { name: string; last_updated_at: string | null; status: string | null }[];
  binance_snapshot_at: string | null;
}

export const SYNC_POLL_MS = 2000;

// Last `running` seen per client, shared by every observer (Shell + Ajustes): one invalidation per finished run.
const lastRunning = new WeakMap<QueryClient, boolean>();

/** Sync status, polled while a run is going. When a run ends (started here, in another tab or by the CLI)
 *  every number on screen may have changed, so all queries are invalidated, once. */
export function useSyncStatus(pollMs = SYNC_POLL_MS) {
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["syncStatus"],
    queryFn: () => api<SyncStatus>("/sync/status"),
    refetchInterval: (q) => (q.state.data?.running ? pollMs : false),
    staleTime: 0,
  });
  const running = status.data?.running ?? false;
  useEffect(() => {
    if (status.data === undefined) return;
    if (lastRunning.get(qc) && !running) void qc.invalidateQueries();
    lastRunning.set(qc, running);
  }, [running, status.data, qc]);
  return status;
}
