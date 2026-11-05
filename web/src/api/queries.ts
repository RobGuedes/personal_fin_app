import { keepPreviousData, useQuery, type QueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { components } from "./schema";

export type Taxonomy = components["schemas"]["TaxonomyOut"];

export type SankeyResponse = components["schemas"]["SankeyOut"];

/** `period` = month:YYYY-MM | last12 | year:YYYY. */
export function useSankey(period: string | null) {
  return useQuery({
    queryKey: ["sankey", period],
    queryFn: () => api<SankeyResponse>(`/sankey?period=${encodeURIComponent(period ?? "")}`),
    enabled: !!period,
    placeholderData: keepPreviousData,
  });
}

export type PanoramaResponse = components["schemas"]["PanoramaOut"];
export type PnlResponse = components["schemas"]["PnlOut"];
export type ChannelsResponse = components["schemas"]["ChannelsOut"];
export type CounterpartiesResponse = components["schemas"]["CounterpartiesOut"];
export type CategoryPageResponse = components["schemas"]["CategoryPageOut"];

function periodQuery<T>(key: string, path: string, period: string | null, enabled = true) {
  return {
    queryKey: [key, path, period],
    queryFn: () => api<T>(`${path}?period=${encodeURIComponent(period ?? "")}`),
    placeholderData: keepPreviousData,
    enabled: enabled && !!period,
  };
}

/** Panorama queries; `period` = month:YYYY-MM | last12 | year:YYYY. */
export const usePanorama = (period: string | null) => useQuery(periodQuery<PanoramaResponse>("panorama", "/panorama", period));
export const usePnl = (period: string | null, enabled = true) => useQuery(periodQuery<PnlResponse>("pnl", "/pnl", period, enabled));
export const useChannels = (period: string | null, enabled = true) =>
  useQuery(periodQuery<ChannelsResponse>("channels", "/channels", period, enabled));
export const useCounterparties = (period: string | null, enabled = true) =>
  useQuery(periodQuery<CounterpartiesResponse>("counterparties", "/counterparties", period, enabled));
export const useCategoryPage = (id: string, period: string | null) =>
  useQuery(periodQuery<CategoryPageResponse>("category", `/categories/${encodeURIComponent(id)}`, period));

/** The server's current month (America/Sao_Paulo), as Início does; month:/year: periods are validated against it. */
export function useCurrentMonth() {
  return useQuery({
    queryKey: ["summary", "current"],
    queryFn: () => api<{ month: string; day: number }>("/summary/month"),
  });
}

export type NetWorthResponse = components["schemas"]["NetWorthOut"];
export type ContributionsResponse = components["schemas"]["ContributionsOut"];
/** One daily snapshot (the API schema types the list loosely). */
export interface NetWorthPoint { date: string; accounts: number; investments: number; crypto: number; cards: number; total: number }

export const useNetWorth = () => useQuery({ queryKey: ["networth"], queryFn: () => api<NetWorthResponse>("/networth") });
export const useNetWorthHistory = () =>
  useQuery({ queryKey: ["networthHistory"], queryFn: () => api<NetWorthPoint[]>("/networth/history") });
/** `period` = year:YYYY. */
export const useContributions = (period: string | null) =>
  useQuery({
    queryKey: ["contributions", period],
    queryFn: () => api<ContributionsResponse>(`/networth/contributions?period=${encodeURIComponent(period ?? "")}`),
    enabled: !!period,
  });

export function useTaxonomy() {
  return useQuery({ queryKey: ["taxonomy"], queryFn: () => api<Taxonomy>("/taxonomy"), staleTime: 5 * 60_000 });
}

export type AccountOut = components["schemas"]["AccountOut"];
export const useAccounts = () =>
  useQuery({ queryKey: ["accounts"], queryFn: () => api<AccountOut[]>("/accounts"), staleTime: 5 * 60_000 });

/** A classification change (or a new rule, which re-runs classify) can move every number and list on screen,
 *  including Ajustes' rules, transfer audit and color slots: refresh everything rather than keep a list of keys. */
export function invalidateAfterMutation(qc: QueryClient): Promise<unknown> {
  return qc.invalidateQueries();
}
