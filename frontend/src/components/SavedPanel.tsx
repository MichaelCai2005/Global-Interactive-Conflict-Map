import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { type SavedSearch, useSavedSearches, useSavedSearchMutations } from "../api/account";
import { request } from "../api/client";
import type { Board } from "../board/api";
import { type DateWindow, formatDate } from "../lib/dates";
import type { Filters } from "../state/dashboard";

interface Props {
  filters: Filters;
  window: DateWindow;
  /** The current view as an address-bar query, the same as a shared link. */
  query: string;
  onRestore(query: string): void;
  onBoard(boardId: number): void;
}

/** Map views a person keeps, and the board topics they've searched, to come back to. */
export function SavedPanel({ filters, window, query, onRestore, onBoard }: Props) {
  const { data: searches, isLoading, error } = useSavedSearches(true);
  const { create, update, remove } = useSavedSearchMutations();
  const [name, setName] = useState<string | null>(null);
  const client = useQueryClient();
  const rerun = useMutation({
    mutationFn: (s: SavedSearch) => request<Board>("/boards/topic", { method: "POST", json: s.params }),
    onSuccess: (board) => {
      void client.invalidateQueries({ queryKey: ["boards"] });
      void client.invalidateQueries({ queryKey: ["searches"] });
      onBoard(board.id);
    },
  });

  const views = searches?.filter((s) => s.kind === "map") ?? [];
  const topics = searches?.filter((s) => s.kind === "topic") ?? [];
  const suggested = `${filters.country ?? "World"}, ${formatDate(window.start)} – ${formatDate(window.end)}`;

  const open = (s: SavedSearch) => {
    update.mutate({ id: s.id, used: true });
    onRestore(String(s.params.query ?? ""));
  };

  return (
    <div className="panel-body">
      <p className="muted small">
        Keep a map view (its filters, time window and place) to reopen later. Topics you search on the Boards tab
        are listed here too, to run again.
      </p>
      {name === null ? (
        <div className="button-row">
          <button className="primary" onClick={() => setName(suggested)}>
            + Save this view
          </button>
        </div>
      ) : (
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim()) return;
            create.mutate(
              { name: name.trim(), kind: "map", params: { query } },
              { onSuccess: () => setName(null) },
            );
          }}
        >
          <input aria-label="Name" autoFocus maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
          <button type="submit" disabled={create.isPending}>
            Save
          </button>
          <button type="button" className="ghost" onClick={() => setName(null)}>
            Cancel
          </button>
        </form>
      )}
      {create.error && <p className="error small">{create.error.message}</p>}

      <h3 className="section-title">Saved views</h3>
      {isLoading ? (
        <p className="muted">Loading…</p>
      ) : error ? (
        <p className="error">{error.message}</p>
      ) : views.length === 0 ? (
        <p className="empty small">No saved views yet. Set up the map the way you want it, then save it.</p>
      ) : (
        <ul className="cards">
          {views.map((s) => (
            <li key={s.id} className="card">
              <div className="card-head">
                <button className="link-button card-title" onClick={() => open(s)}>
                  {s.name}
                </button>
                <button className="link-button danger small" onClick={() => remove.mutate(s.id)}>
                  Delete
                </button>
              </div>
              <div className="small muted">{describeQuery(String(s.params.query ?? ""))}</div>
            </li>
          ))}
        </ul>
      )}

      <h3 className="section-title">Topic searches</h3>
      {rerun.error && <p className="error small">{rerun.error.message}</p>}
      {topics.length === 0 ? (
        <p className="empty small">Topics you search on the Boards tab show up here.</p>
      ) : (
        <ul className="cards">
          {topics.map((s) => (
            <li key={s.id} className="card">
              <div className="card-head">
                <span className="card-title">{s.name}</span>
                <button className="link-button danger small" onClick={() => remove.mutate(s.id)}>
                  Delete
                </button>
              </div>
              <div className="card-actions">
                <span className="small muted">
                  {s.last_used_at ? `Last run ${formatDate(s.last_used_at.slice(0, 10))}` : ""}
                </span>
                <button disabled={rerun.isPending} onClick={() => rerun.mutate(s)}>
                  {rerun.isPending && rerun.variables?.id === s.id ? "Searching…" : "Run again"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** A short reading of a saved view's query: its window and filters. */
export function describeQuery(query: string): string {
  const q = new URLSearchParams(query);
  const parts: string[] = [];
  const from = q.get("from");
  const to = q.get("to");
  if (from && to) parts.push(`${formatDate(from)} – ${formatDate(to)}`);
  if (q.get("country")) parts.push(q.get("country")!);
  if (q.get("source")) parts.push(q.get("source")!.split(",").join(", "));
  if (q.get("class")) parts.push(q.get("class") === "violent" ? "violence only" : "signals only");
  return parts.join(" · ") || "Whole map";
}
