import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FeatureCollection } from "geojson";
import { request } from "../api/client";

// Shapes of backend/app/boards/schemas.py.

export type Status = "suggested" | "accepted" | "rejected";
export type NodeKind = "article" | "place" | "actor" | "claim" | "event" | "flight" | "fire" | "vessel" | "note";

export interface BoardNode {
  id: number;
  key: string;
  kind: NodeKind;
  label: string;
  detail: string;
  event_id: number | null;
  latitude: number | null;
  longitude: number | null;
  geo_basis: string | null;
  time_start: string | null;
  time_end: string | null;
  source_name: string | null;
  source_url: string | null;
  quote: string | null;
  status: Status;
  created_by: "user" | "rule" | "ai";
  attributes: Record<string, unknown>;
}

export interface BoardLink {
  id: number;
  from_node_id: number;
  to_node_id: number;
  rule: string;
  reason: string;
  evidence: Record<string, unknown>;
  confidence: number;
  status: Status;
  created_by: "user" | "rule" | "ai";
}

export interface Board {
  id: number;
  title: string;
  origin: "article" | "topic" | "manual";
  prompt: string;
  source_url: string | null;
  anchor_date: string | null;
  extractor: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
  nodes: BoardNode[];
  links: BoardLink[];
}

export interface BoardSummary {
  id: number;
  title: string;
  origin: Board["origin"];
  source_url: string | null;
  anchor_date: string | null;
  extractor: string | null;
  created_at: string;
  updated_at: string;
  nodes: number;
  links: number;
  accepted: number;
}

export interface DraftInput {
  url?: string;
  text?: string;
  title?: string;
  published?: string;
  lookback_days?: number;
}

export type Include = "accepted" | "all";

const API = (import.meta.env.VITE_API_URL as string | undefined) ?? "/api";
const GLOBE = ((import.meta.env.VITE_GLOBE_URL as string | undefined) ?? "http://localhost:4173").replace(/\/+$/, "");

/** gods-eye-view opens a board from this link (src/conflictMap/board.js in the fork). */
export function globeUrl(boardId: number, include: Include): string {
  return `${GLOBE}/?welcome=0&board=${boardId}${include === "all" ? "&include=all" : ""}`;
}

/** A .gevbundle.json the globe imports from its Scenes panel, no API needed. */
export function bundleUrl(boardId: number, include: Include): string {
  return `${API}/boards/${boardId}/bundle?include=${include}`;
}

export function useBoards() {
  return useQuery({ queryKey: ["boards"], queryFn: () => request<BoardSummary[]>("/boards") });
}

export function useBoard(id: number | null) {
  return useQuery({
    queryKey: ["board", id],
    queryFn: () => request<Board>(`/boards/${id}`),
    enabled: id !== null,
  });
}

export function useBoardGeoJson(id: number | null, updatedAt: string | undefined) {
  return useQuery({
    // A board's update time changes with every review, so the map follows edits.
    queryKey: ["board-geojson", id, updatedAt],
    queryFn: () => request<FeatureCollection>(`/boards/${id}/geojson?include=all`),
    enabled: id !== null && updatedAt !== undefined,
  });
}

export function useBoardMutations(id: number | null) {
  const client = useQueryClient();
  const settle = (board?: Board) => {
    if (board) client.setQueryData(["board", board.id], board);
    void client.invalidateQueries({ queryKey: ["board", id] });
    void client.invalidateQueries({ queryKey: ["boards"] });
  };
  const draft = useMutation({
    mutationFn: (input: DraftInput) => request<Board>("/boards/draft", { method: "POST", json: input }),
    onSuccess: settle,
  });
  const topic = useMutation({
    mutationFn: (input: { topic: string; days: number }) =>
      request<Board>("/boards/topic", { method: "POST", json: input }),
    onSuccess: settle,
  });
  const create = useMutation({
    mutationFn: (input: { title: string; anchor_date?: string }) =>
      request<Board>("/boards", { method: "POST", json: input }),
    onSuccess: settle,
  });
  const review = useMutation({
    mutationFn: (input: { status: Status; node_ids?: number[]; link_ids?: number[] }) =>
      request<Board>(`/boards/${id}/review`, { method: "POST", json: input }),
    onSuccess: settle,
  });
  const expand = useMutation({
    mutationFn: (nodeId: number) => request<Board>(`/boards/${id}/nodes/${nodeId}/expand`, { method: "POST" }),
    onSuccess: settle,
  });
  const link = useMutation({
    mutationFn: (input: { from_node_id: number; to_node_id: number; reason: string }) =>
      request<BoardLink>(`/boards/${id}/links`, { method: "POST", json: input }),
    onSuccess: () => settle(),
  });
  const note = useMutation({
    mutationFn: (input: { label: string; latitude: number; longitude: number; time_start?: string; detail?: string }) =>
      request<BoardNode>(`/boards/${id}/nodes`, { method: "POST", json: { kind: "note", ...input } }),
    onSuccess: () => settle(),
  });
  const remove = useMutation({
    mutationFn: (boardId: number) => request<void>(`/boards/${boardId}`, { method: "DELETE" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["boards"] }),
  });
  return { draft, topic, create, review, expand, link, note, remove };
}
