import { useState } from "react";
import { useTaskMutations, useTasks, useWatchlist } from "../api/hooks";
import type { Task, TaskPriority, TaskStatus, WatchItem } from "../api/types";
import { formatDate } from "../lib/dates";
import { eventTypeLabel } from "../lib/format";

interface Props {
  onEvent(event: NonNullable<Task["event"]>): void;
  onWatchItem(item: WatchItem): void;
}

const COLUMNS: { status: TaskStatus; label: string }[] = [
  { status: "open", label: "Open" },
  { status: "in_progress", label: "In progress" },
  { status: "done", label: "Done" },
];

const PRIORITY_ORDER: Record<TaskPriority, number> = { high: 0, normal: 1, low: 2 };

export function TasksPanel({ onEvent, onWatchItem }: Props) {
  const { data: tasks, isLoading, error } = useTasks();
  const watchlist = useWatchlist().data ?? [];
  const { create } = useTaskMutations();
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState<TaskPriority>("normal");
  const [showDone, setShowDone] = useState(false);

  return (
    <div className="panel-body">
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!title.trim()) return;
          create.mutate({ title: title.trim(), priority }, { onSuccess: () => setTitle("") });
        }}
      >
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="New task…" aria-label="New task title" />
        <select value={priority} onChange={(e) => setPriority(e.target.value as TaskPriority)} aria-label="Priority">
          <option value="high">High</option>
          <option value="normal">Normal</option>
          <option value="low">Low</option>
        </select>
        <button type="submit" disabled={create.isPending || !title.trim()}>
          Add
        </button>
      </form>
      <p className="muted small">Tip: open an event on the map to create a task linked to it.</p>
      {error && <p className="error">Could not load tasks: {error.message}</p>}
      {isLoading && <p className="muted">Loading…</p>}
      {tasks?.length === 0 && <p className="empty">No tasks yet.</p>}

      {COLUMNS.map(({ status, label }) => {
        const group = (tasks ?? [])
          .filter((t) => t.status === status)
          .sort((a, b) => PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority] || b.id - a.id);
        if (group.length === 0) return null;
        const collapsed = status === "done" && !showDone;
        return (
          <section key={status}>
            <h3>
              {label} <span className="muted">{group.length}</span>
              {status === "done" && (
                <button className="link-button small" onClick={() => setShowDone(!showDone)}>
                  {showDone ? "Hide" : "Show"}
                </button>
              )}
            </h3>
            {!collapsed && (
              <ul className="cards">
                {group.map((t) => (
                  <TaskCard
                    key={t.id}
                    task={t}
                    watchItem={watchlist.find((w) => w.id === t.watch_item_id)}
                    onEvent={onEvent}
                    onWatchItem={onWatchItem}
                  />
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}

function TaskCard({
  task,
  watchItem,
  onEvent,
  onWatchItem,
}: Props & { task: Task; watchItem: WatchItem | undefined }) {
  const { update, remove } = useTaskMutations();
  const [editing, setEditing] = useState(false);
  const [notes, setNotes] = useState(task.notes);

  return (
    <li className={`card task priority-${task.priority}${task.status === "done" ? " is-done" : ""}`}>
      <div className="card-head">
        <span className="task-title">{task.title}</span>
        {task.priority !== "normal" && <span className={`badge badge-${task.priority}`}>{task.priority}</span>}
      </div>
      {task.event && (
        <button className="link-chip" onClick={() => onEvent(task.event!)}>
          {eventTypeLabel(task.event.event_type)} · {task.event.location_name ?? task.event.country ?? "event"} ·{" "}
          {formatDate(task.event.event_date)}
        </button>
      )}
      {watchItem && (
        <button className="link-chip" onClick={() => onWatchItem(watchItem)}>
          Watching: {watchItem.name}
        </button>
      )}
      {editing ? (
        <form
          className="notes-form"
          onSubmit={(e) => {
            e.preventDefault();
            update.mutate({ id: task.id, notes }, { onSuccess: () => setEditing(false) });
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
        task.notes && <p className="notes">{task.notes}</p>
      )}
      <div className="card-actions">
        <select
          value={task.status}
          aria-label="Status"
          onChange={(e) => update.mutate({ id: task.id, status: e.target.value as TaskStatus })}
        >
          {COLUMNS.map((c) => (
            <option key={c.status} value={c.status}>
              {c.label}
            </option>
          ))}
        </select>
        <button className="link-button small" onClick={() => setEditing(true)}>
          {task.notes ? "Edit notes" : "Add notes"}
        </button>
        <button
          className="link-button small danger"
          onClick={() => globalThis.confirm(`Delete "${task.title}"?`) && remove.mutate(task.id)}
        >
          Delete
        </button>
      </div>
    </li>
  );
}
