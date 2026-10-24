import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FeatureCollection } from "geojson";
import { useEffect, useState } from "react";
import { BASE, authHeaders, request, sessionToken } from "../api/client";

// Shapes of backend/app/boards/schemas.py.

export type Status = "suggested" | "accepted" | "rejected";
export type NodeKind =
  | "article"
  | "place"
  | "actor"
  | "claim"
  | "event"
  | "flight"
  | "fire"
  | "vessel"
  | "note"
  | "link";

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
  /** Where the card sits on the canvas, once someone has moved it. */
  board_x: number | null;
  board_y: number | null;
  /** A public link, or /boards/images/<id> for an uploaded picture (see imageSrc). */
  image_url: string | null;
}

/** A card added by hand: a note (an idea, a picture) or a link to another page. */
export interface CardInput {
  kind: "note" | "link";
  label: string;
  detail?: string;
  source_url?: string;
  image_url?: string;
  latitude?: number;
  longitude?: number;
  time_start?: string;
  board_x?: number;
  board_y?: number;
}

/** Fields a card can change; null clears a picture, link or map place. */
export interface NodeChanges {
  status?: Status;
  label?: string;
  detail?: string;
  source_url?: string | null;
  image_url?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  board_x?: number;
  board_y?: number;
}

export interface Position {
  id: number;
  x: number;
  y: number;
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

/** Where the browser loads a card's picture from: uploaded ones come from this API. */
export function imageSrc(url: string | null): string | null {
  if (!url) return null;
  return url.startsWith("/boards/images/") ? `${BASE}${url}` : url;
}

/** imageSrc for an <img>. With a sign-in token (an API on another site), an uploaded
 * picture on a private board is fetched with the token, since an <img> can't send it. */
export function useImageSrc(url: string | null): string | null {
  const src = imageSrc(url);
  const withToken = !!src && src !== url && !!sessionToken();
  const [blob, setBlob] = useState<string | null>(null);
  useEffect(() => {
    if (!withToken || !src) return;
    let objectUrl: string | null = null;
    let live = true;
    fetch(src, { headers: authHeaders() })
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => {
        if (b && live) setBlob((objectUrl = URL.createObjectURL(b)));
      })
      .catch(() => undefined);
    return () => {
      live = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setBlob(null);
    };
  }, [src, withToken]);
  return withToken ? blob : src;
}

/** The site a link points to, for card captions ("reuters.com"). */
export function siteOf(url: string | null): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

async function uploadImage(boardId: number, file: File): Promise<{ id: number; url: string }> {
  const form = new FormData();
  form.append("file", file);
  return request(`/boards/${boardId}/images`, { method: "POST", body: form });
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
  // Moving cards shows at once; the save happens behind it and is not refetched.
  const placeLocally = (positions: Position[]) => {
    const at = new Map(positions.map((p) => [p.id, p]));
    client.setQueryData<Board>(["board", id], (board) =>
      board && {
        ...board,
        nodes: board.nodes.map((n) => {
          const p = at.get(n.id);
          return p ? { ...n, board_x: p.x, board_y: p.y } : n;
        }),
      },
    );
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
    mutationFn: (input: { from_node_id: number; to_node_id: number; reason?: string }) =>
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
  const card = useMutation({
    mutationFn: (input: CardInput & { file?: File }) => {
      const { file, ...fields } = input;
      const save = (image_url?: string) =>
        request<BoardNode>(`/boards/${id}/nodes`, { method: "POST", json: { ...fields, image_url } });
      return file ? uploadImage(id!, file).then((img) => save(img.url)) : save(fields.image_url || undefined);
    },
    onSuccess: () => settle(),
  });
  const updateNode = useMutation({
    mutationFn: ({ nodeId, changes }: { nodeId: number; changes: NodeChanges }) =>
      request<BoardNode>(`/boards/${id}/nodes/${nodeId}`, { method: "PATCH", json: changes }),
    onSuccess: () => settle(),
  });
  const picture = useMutation({
    mutationFn: async ({ nodeId, file }: { nodeId: number; file: File }) => {
      const img = await uploadImage(id!, file);
      return request<BoardNode>(`/boards/${id}/nodes/${nodeId}`, { method: "PATCH", json: { image_url: img.url } });
    },
    onSuccess: () => settle(),
  });
  const deleteNode = useMutation({
    mutationFn: (nodeId: number) => request<void>(`/boards/${id}/nodes/${nodeId}`, { method: "DELETE" }),
    onSuccess: () => settle(),
  });
  const updateLink = useMutation({
    mutationFn: ({ linkId, changes }: { linkId: number; changes: { status?: Status; reason?: string } }) =>
      request<BoardLink>(`/boards/${id}/links/${linkId}`, { method: "PATCH", json: changes }),
    onSuccess: () => settle(),
  });
  const deleteLink = useMutation({
    mutationFn: (linkId: number) => request<void>(`/boards/${id}/links/${linkId}`, { method: "DELETE" }),
    onSuccess: () => settle(),
  });
  const article = useMutation({
    mutationFn: (input: DraftInput & { board_x?: number; board_y?: number }) =>
      request<Board>(`/boards/${id}/articles`, { method: "POST", json: input }),
    onSuccess: settle,
  });
  const layout = useMutation({
    mutationFn: (positions: Position[]) => {
      placeLocally(positions);
      return request<{ saved: number }>(`/boards/${id}/layout`, { method: "POST", json: { positions } });
    },
    // A failed save puts the cards back where the server has them.
    onError: () => void client.invalidateQueries({ queryKey: ["board", id] }),
  });
  return {
    draft,
    topic,
    create,
    review,
    expand,
    link,
    note,
    remove,
    card,
    updateNode,
    picture,
    deleteNode,
    updateLink,
    deleteLink,
    article,
    layout,
  };
}
