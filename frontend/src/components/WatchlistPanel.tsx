import { useState } from "react";
import type { Scope } from "../api/client";
import { useSummary, useTaskMutations, useTimeline, useWatchlist, useWatchlistMutations } from "../api/hooks";
import type { Bbox, Interval, WatchItem } from "../api/types";
import { type DateWindow, daysBetween, describeLength, previousWindow } from "../lib/dates";
import { formatCompact, percentChange, plural } from "../lib/format";
import { describeBbox, parseBbox } from "../lib/geo";
import type { Filters } from "../state/dashboard";
import { Change } from "./OverviewPanel";
import { Sparkline } from "./Sparkline";

interface Props {
  filters: Filters;
  window: DateWindow;
  domain: DateWindow;
  interval: Interval;
  viewBbox: Bbox | null;
  onOpen(item: WatchItem): void;
}

export function WatchlistPanel({ filters, window, domain, interval, viewBbox, onOpen }: Props) {
  const { data: items, isLoading, error } = useWatchlist();
  const { create } = useWatchlistMutations();
  const [draft, setDraft] = useState<{ name: string; country: string | null; bbox: string | null } | null>(null);

  const startDraft = (kind: "view" | "country") => {
    if (kind === "country" && filters.country) {
      setDraft({ name: filters.country, country: filters.country, bbox: null });
    } else if (viewBbox) {
      setDraft({ name: describeBbox(viewBbox), country: null, bbox: viewBbox.join(",") });
    }
  };

  return (
    <div className="panel-body">
      <p className="muted small">
        Places to keep an eye on. Each card compares violent events in the current window with
        the {describeLength(daysBetween(window.start, window.end) + 1)} before it, under the
        current filters.
      </p>
      <div className="button-row">
        <button
          onClick={() => startDraft("view")}
          disabled={!viewBbox}
          title={viewBbox ? "Watch the area the map shows now" : "Zoom in to an area first"}
        >
          + Watch this map view
        </button>
        {filters.country && <button onClick={() => startDraft("country")}>+ Watch {filters.country}</button>}
      </div>
      {draft && (
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (!draft.name.trim()) return;
            create.mutate({ ...draft, name: draft.name.trim() }, { onSuccess: () => setDraft(null) });
          }}
        >
          <input
            autoFocus
            aria-label="Name for this watch item"
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
          <button type="submit" disabled={create.isPending}>
            Save
          </button>
          <button type="button" className="ghost" onClick={() => setDraft(null)}>
            Cancel
          </button>
        </form>
      )}
      {create.error && <p className="error small">{create.error.message}</p>}
      {error && <p className="error">Could not load the watchlist: {error.message}</p>}
      {isLoading && <p className="muted">Loading…</p>}
      {items?.length === 0 && !draft && (
        <p className="empty">Nothing watched yet. Zoom the map to an area or pick a country, then add it here.</p>
      )}
      <ul className="cards">
        {items?.map((item) => (
          <WatchCard
            key={item.id}
            item={item}
            filters={filters}
            window={window}
            domain={domain}
            interval={interval}
            onOpen={() => onOpen(item)}
          />
        ))}
      </ul>
    </div>
  );
}

function WatchCard({
  item,
  filters,
  window,
  domain,
  interval,
  onOpen,
}: Omit<Props, "viewBbox" | "onOpen"> & { item: WatchItem; onOpen(): void }) {
  const { remove, update } = useWatchlistMutations();
  const tasks = useTaskMutations();
  const base: Scope = {
    filters: item.country ? { ...filters, country: item.country } : filters,
    bbox: parseBbox(item.bbox),
  };
  const timeline = useTimeline({ ...base, window: domain }, interval);
  const now = useSummary({ ...base, window });
  const before = useSummary({ ...base, window: previousWindow(window) });
  const [editing, setEditing] = useState(false);
  const [notes, setNotes] = useState(item.notes);
  const change =
    now.data && before.data ? percentChange(now.data.violent_events, before.data.violent_events) : undefined;

  return (
    <li className="card">
      <div className="card-head">
        <button className="card-title" onClick={onOpen} title="Show on the map">
          {item.name}
        </button>
        <span className="muted small">{item.country ? "Country" : "Area"}</span>
      </div>
      <button className="spark-button" onClick={onOpen} aria-label={`Show ${item.name} on the map`}>
        <Sparkline buckets={timeline.data?.buckets ?? []} interval={interval} domain={domain} window={window} />
      </button>
      <div className="card-stats">
        <span>
          <strong>{now.data ? formatCompact(now.data.violent_events) : "–"}</strong> violent
        </span>
        {change !== undefined && <Change change={change} />}
        <span className="muted">{now.data ? plural(now.data.fatalities, "death") : ""}</span>
        <span className="muted">{now.data ? plural(now.data.signal_events, "signal") : ""}</span>
      </div>
      {editing ? (
        <form
          className="notes-form"
          onSubmit={(e) => {
            e.preventDefault();
            update.mutate({ id: item.id, notes }, { onSuccess: () => setEditing(false) });
          }}
        >
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} aria-label="Notes" />
          <div className="button-row">
            <button type="submit">Save notes</button>
            <button type="button" className="ghost" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        item.notes && <p className="notes">{item.notes}</p>
      )}
      <div className="card-actions">
        <button className="link-button small" onClick={() => setEditing(true)}>
          {item.notes ? "Edit notes" : "Add notes"}
        </button>
        <button
          className="link-button small"
          onClick={() => tasks.create.mutate({ title: `Review recent activity in ${item.name}`, watch_item_id: item.id })}
        >
          Create task
        </button>
        <button
          className="link-button small danger"
          onClick={() => confirmAction(`Stop watching ${item.name}?`) && remove.mutate(item.id)}
        >
          Remove
        </button>
      </div>
      {tasks.create.isSuccess && <p className="muted small">Task added to the task list.</p>}
    </li>
  );
}

// `window` is a prop name in this file, so the browser's confirm is reached through globalThis.
const confirmAction = (message: string) => globalThis.confirm(message);
