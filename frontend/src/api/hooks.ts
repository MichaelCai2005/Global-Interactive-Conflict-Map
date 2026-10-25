import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type Scope, queryString, request, scopeParams } from "./client";
import type {
  CountrySummary,
  EventDetail,
  EventPage,
  Facets,
  Interval,
  MapLayer,
  Summary,
  Task,
  TaskInput,
  Timeline,
  WatchItem,
} from "./types";

export const MAX_POINTS = 15_000;

export function useFacets() {
  return useQuery({
    queryKey: ["facets"],
    queryFn: () => request<Facets>("/facets"),
    staleTime: Infinity,
  });
}

export function mapLayerQuery(scope: Scope, cell: number) {
  const params = { ...scopeParams(scope), cell, max_points: MAX_POINTS };
  return {
    queryKey: ["map", params],
    queryFn: () => request<MapLayer>(`/map${queryString(params)}`),
    staleTime: 5 * 60_000,
  };
}

export function useMapLayer(scope: Scope, cell: number, enabled: boolean) {
  return useQuery({ ...mapLayerQuery(scope, cell), enabled, placeholderData: keepPreviousData });
}

export function useTimeline(scope: Scope, interval: Interval, enabled = true) {
  const params = { ...scopeParams(scope), interval };
  return useQuery({
    queryKey: ["timeline", params],
    queryFn: () => request<Timeline>(`/timeline${queryString(params)}`),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useSummary(scope: Scope, enabled = true) {
  const params = scopeParams(scope);
  return useQuery({
    queryKey: ["summary", params],
    queryFn: () => request<Summary>(`/summary${queryString(params)}`),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useCountries(scope: Scope, limit: number, enabled = true) {
  const params = { ...scopeParams(scope), limit };
  return useQuery({
    queryKey: ["countries", params],
    queryFn: () => request<CountrySummary[]>(`/countries${queryString(params)}`),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useDeadliest(scope: Scope, limit: number, enabled = true) {
  return useViolentEvents(scope, "fatalities", limit, enabled);
}

/** Violent events under the scope, deadliest or most reported (by news articles) first. */
export function useViolentEvents(scope: Scope, sort: "fatalities" | "reports", limit: number, enabled = true) {
  const params = { ...scopeParams(scope), sort, violent: true, limit };
  return useQuery({
    queryKey: ["events", params],
    queryFn: () => request<EventPage>(`/events${queryString(params)}`),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useEvent(id: number | null) {
  return useQuery({
    queryKey: ["event", id],
    queryFn: () => request<EventDetail>(`/events/${id}`),
    enabled: id !== null,
    staleTime: Infinity,
  });
}

// The watchlist and tasks are small, so every change refetches the whole list.

export function useWatchlist() {
  return useQuery({ queryKey: ["watchlist"], queryFn: () => request<WatchItem[]>("/watchlist") });
}

export function useWatchlistMutations() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: ["watchlist"] });
  return {
    create: useMutation({
      mutationFn: (item: Pick<WatchItem, "name" | "country" | "bbox"> & { notes?: string }) =>
        request<WatchItem>("/watchlist", { method: "POST", json: item }),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: ({ id, ...patch }: Partial<Pick<WatchItem, "name" | "notes">> & { id: number }) =>
        request<WatchItem>(`/watchlist/${id}`, { method: "PATCH", json: patch }),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: number) => request<void>(`/watchlist/${id}`, { method: "DELETE" }),
      onSuccess: () => {
        refresh();
        // Tasks that pointed at the item lose the link.
        client.invalidateQueries({ queryKey: ["tasks"] });
      },
    }),
  };
}

export function useTasks(enabled = true) {
  return useQuery({ queryKey: ["tasks"], queryFn: () => request<Task[]>("/tasks"), enabled });
}

export function useTaskMutations() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: ["tasks"] });
  return {
    create: useMutation({
      mutationFn: (task: TaskInput) => request<Task>("/tasks", { method: "POST", json: task }),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: ({ id, ...patch }: Partial<TaskInput> & { id: number }) =>
        request<Task>(`/tasks/${id}`, { method: "PATCH", json: patch }),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: number) => request<void>(`/tasks/${id}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
  };
}
