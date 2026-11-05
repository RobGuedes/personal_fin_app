import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";

const MAX_RETRIES = 2;

/** A 4xx will not change on retry (unknown id, invalid month): show it at once. 5xx/network: retry twice. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < MAX_RETRIES;
}

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: shouldRetry } },
  });
}
