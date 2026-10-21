import { useMemo, useState } from "react";
import { type DateWindow, addDays, formatDate } from "../lib/dates";
import { plural } from "../lib/format";
import {
  type Board,
  type BoardLink,
  type BoardNode,
  type Include,
  type Status,
  bundleUrl,
  globeUrl,
  useBoard,
  useBoardMutations,
  useBoards,
} from "./api";
import "./board.css";
import { KIND_LABELS, RULE_LABELS, nodeColor } from "./style";

interface Props {
  boardId: number | null;
  selectedNodeId: number | null;
  mapCenter: { lon: number; lat: number };
  onOpen(boardId: number | null): void;
  onSelectNode(nodeId: number | null): void;
  onFocus(lon: number, lat: number): void;
  /** Point the timeline at a board's story: its lookback window up to its date. */
  onWindow(window: DateWindow): void;
}

export function BoardPanel(props: Props) {
  return props.boardId === null ? (
    <BoardList onOpen={props.onOpen} onWindow={props.onWindow} />
  ) : (
    <BoardView {...props} boardId={props.boardId} />
  );
}

/** The window a board's story covers on the timeline. */
export function storyWindow(board: Pick<Board, "anchor_date">): DateWindow | null {
  if (!board.anchor_date) return null;
  return { start: addDays(board.anchor_date, -60), end: addDays(board.anchor_date, 3) };
}

// --- Board list and new boards ------------------------------------------------------

function BoardList({ onOpen, onWindow }: Pick<Props, "onOpen" | "onWindow">) {
  const { data: boards, isLoading, error } = useBoards();
  const open = (board: Pick<Board, "id" | "anchor_date">) => {
    const window = storyWindow(board);
    if (window) onWindow(window);
    onOpen(board.id);
  };
  return (
    <div className="panel-body board-panel">
      <p className="muted small">
        Paste a news article or name a topic. The board lists the places, groups and events it
        connects to, each link with its reason and source. Accept what holds up, then present it
        on the 3D globe.
      </p>
      <NewBoard onCreated={open} />
      <h3 className="section-title">Boards</h3>
      {error && <p className="error">Could not load boards: {error.message}</p>}
      {isLoading && <p className="muted">Loading…</p>}
      {boards?.length === 0 && <p className="empty">No boards yet.</p>}
      <ul className="cards">
        {boards?.map((b) => (
          <li key={b.id} className="card">
            <button className="card-title" onClick={() => open(b)}>
              {b.title}
            </button>
            <div className="small muted">
              {b.anchor_date ? formatDate(b.anchor_date) : "No date"} · {b.origin} ·{" "}
              {plural(b.nodes, "item")}, {b.accepted} accepted
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function NewBoard({ onCreated }: { onCreated(board: Board): void }) {
  const [mode, setMode] = useState<"article" | "topic" | "blank">("article");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [paste, setPaste] = useState(false);
  const [title, setTitle] = useState("");
  const [published, setPublished] = useState("");
  const [topic, setTopic] = useState("");
  const { draft, topic: fromTopic, create } = useBoardMutations(null);
  const pending = draft.isPending || fromTopic.isPending || create.isPending;
  const error = draft.error ?? fromTopic.error ?? create.error;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === "article") {
      draft.mutate(
        {
          url: url.trim() || undefined,
          text: paste ? text.trim() || undefined : undefined,
          title: title.trim() || undefined,
          published: published || undefined,
        },
        { onSuccess: onCreated },
      );
    } else if (mode === "topic") {
      fromTopic.mutate({ topic: topic.trim(), days: 14 }, { onSuccess: onCreated });
    } else {
      create.mutate(
        { title: title.trim() || "Untitled board", anchor_date: published || undefined },
        { onSuccess: onCreated },
      );
    }
  };

  const ready =
    mode === "article" ? Boolean(url.trim() || (paste && text.trim())) : mode === "topic" ? topic.trim().length >= 3 : true;

  return (
    <form className="board-new" onSubmit={submit}>
      <div className="segmented small" role="tablist" aria-label="Start a board from">
        {(
          [
            ["article", "Article"],
            ["topic", "Topic"],
            ["blank", "Blank"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={mode === value}
            className={mode === value ? "is-on" : ""}
            onClick={() => setMode(value)}
          >
            {label}
          </button>
        ))}
      </div>
      {mode === "article" && (
        <>
          <label className="field">
            <span>Article link</span>
            <input type="url" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} />
          </label>
          <label className="check small">
            <input type="checkbox" checked={paste} onChange={(e) => setPaste(e.target.checked)} /> Paste the text
            instead (for paywalled sites)
          </label>
          {paste && (
            <textarea
              aria-label="Article text"
              rows={6}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Paste the article's text here"
            />
          )}
          <div className="field-row">
            <label className="field">
              <span>Title (optional)</span>
              <input value={title} onChange={(e) => setTitle(e.target.value)} />
            </label>
            <label className="field">
              <span>Story date</span>
              <input type="date" value={published} onChange={(e) => setPublished(e.target.value)} />
            </label>
          </div>
        </>
      )}
      {mode === "topic" && (
        <label className="field">
          <span>Topic</span>
          <input
            placeholder="e.g. Wagner in Mali, Houthi attacks on shipping"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
          />
          <span className="small muted">Reads up to 8 English-language articles from the last 14 days.</span>
        </label>
      )}
      {mode === "blank" && (
        <div className="field-row">
          <label className="field">
            <span>Title</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="field">
            <span>Date</span>
            <input type="date" value={published} onChange={(e) => setPublished(e.target.value)} />
          </label>
        </div>
      )}
      <button type="submit" className="primary" disabled={!ready || pending}>
        {pending ? (mode === "blank" ? "Creating…" : "Reading and linking… (up to a minute)") : "Build board"}
      </button>
      {error && <p className="error small">{error.message}</p>}
    </form>
  );
}

// --- One board ----------------------------------------------------------------------

type ReviewFilter = "suggested" | "accepted" | "rejected" | "all";

function BoardView({
  boardId,
  selectedNodeId,
  mapCenter,
  onOpen,
  onSelectNode,
  onFocus,
  onWindow,
}: Props & { boardId: number }) {
  const { data: board, isLoading, error } = useBoard(boardId);
  const mutations = useBoardMutations(boardId);
  const [filter, setFilter] = useState<ReviewFilter>("suggested");
  const [include, setInclude] = useState<Include>("accepted");
  const [linkFrom, setLinkFrom] = useState<number | null>(null);

  const nodes = useMemo(() => new Map(board?.nodes.map((n) => [n.id, n]) ?? []), [board]);
  if (error) return <div className="panel-body error">Could not load the board: {error.message}</div>;
  if (isLoading || !board) return <div className="panel-body muted">Loading…</div>;

  const counts = {
    suggested: board.links.filter((k) => k.status === "suggested").length,
    accepted: board.links.filter((k) => k.status === "accepted").length,
    rejected: board.links.filter((k) => k.status === "rejected").length,
  };
  const links = board.links
    .filter((k) => filter === "all" || k.status === filter)
    .sort((a, b) => b.confidence - a.confidence);
  const strong = board.links.filter((k) => k.status === "suggested" && k.confidence >= 0.8);
  const accepted = board.nodes.filter((n) => n.status === "accepted").length;
  const setLink = (link: BoardLink, status: Status) => mutations.review.mutate({ status, link_ids: [link.id] });
  const focus = (node: BoardNode | undefined) => {
    if (!node || node.latitude === null || node.longitude === null) return;
    onSelectNode(node.id);
    onFocus(node.longitude, node.latitude);
  };

  return (
    <div className="panel-body board-panel">
      <button className="ghost small back" onClick={() => onOpen(null)}>
        ← All boards
      </button>
      <h2 className="board-title">{board.title}</h2>
      <p className="small muted">
        {board.anchor_date ? formatDate(board.anchor_date) : "No date"} · from {board.origin}
        {board.extractor ? ` · read by ${board.extractor}` : ""}
        {board.source_url && (
          <>
            {" · "}
            <a href={board.source_url} target="_blank" rel="noopener noreferrer">
              source
            </a>
          </>
        )}
      </p>
      {board.notes && <p className="notes small board-notes">{board.notes}</p>}

      <div className="board-present">
        <div className="segmented small" aria-label="What to present">
          <button className={include === "accepted" ? "is-on" : ""} onClick={() => setInclude("accepted")}>
            Accepted ({accepted})
          </button>
          <button className={include === "all" ? "is-on" : ""} onClick={() => setInclude("all")}>
            Everything not rejected
          </button>
        </div>
        <div className="button-row">
          <a className="button primary" href={globeUrl(board.id, include)} target="_blank" rel="noopener noreferrer">
            Open in 3D globe
          </a>
          <a className="button" href={bundleUrl(board.id, include)} download>
            Download for globe
          </a>
          {storyWindow(board) && (
            <button className="ghost" onClick={() => onWindow(storyWindow(board)!)}>
              Show its time
            </button>
          )}
        </div>
      </div>

      <h3 className="section-title">Links to review</h3>
      <div className="segmented small" role="tablist" aria-label="Which links">
        {(["suggested", "accepted", "rejected", "all"] as const).map((f) => (
          <button key={f} role="tab" aria-selected={filter === f} className={filter === f ? "is-on" : ""} onClick={() => setFilter(f)}>
            {f === "suggested" ? `To review (${counts.suggested})` : f === "all" ? "All" : `${f[0]!.toUpperCase()}${f.slice(1)} (${counts[f]})`}
          </button>
        ))}
      </div>
      {filter === "suggested" && strong.length > 1 && (
        <button
          className="small"
          disabled={mutations.review.isPending}
          onClick={() => mutations.review.mutate({ status: "accepted", link_ids: strong.map((k) => k.id) })}
        >
          Accept the {strong.length} links at 80% or more
        </button>
      )}
      {links.length === 0 && <p className="empty small">Nothing here.</p>}
      <ul className="cards board-links">
        {links.map((k) => (
          <LinkCard
            key={k.id}
            link={k}
            from={nodes.get(k.from_node_id)}
            to={nodes.get(k.to_node_id)}
            busy={mutations.review.isPending}
            onStatus={(s) => setLink(k, s)}
            onFocus={focus}
          />
        ))}
      </ul>

      <h3 className="section-title">On the board</h3>
      {linkFrom !== null && (
        <LinkForm
          from={nodes.get(linkFrom)!}
          nodes={board.nodes.filter((n) => n.id !== linkFrom && n.status !== "rejected")}
          pending={mutations.link.isPending}
          error={mutations.link.error}
          onCancel={() => setLinkFrom(null)}
          onSubmit={(to, reason) =>
            mutations.link.mutate(
              { from_node_id: linkFrom, to_node_id: to, reason },
              { onSuccess: () => setLinkFrom(null) },
            )
          }
        />
      )}
      <NodeGroups
        board={board}
        selectedNodeId={selectedNodeId}
        expanding={mutations.expand.isPending ? mutations.expand.variables : null}
        onFocus={focus}
        onExpand={(n) => mutations.expand.mutate(n.id)}
        onStatus={(n, status) => mutations.review.mutate({ status, node_ids: [n.id] })}
        onLink={(n) => setLinkFrom(n.id)}
      />
      {mutations.expand.error && <p className="error small">{mutations.expand.error.message}</p>}
      <NoteForm
        center={mapCenter}
        anchor={board.anchor_date}
        pending={mutations.note.isPending}
        onSubmit={(label, detail) =>
          mutations.note.mutate({
            label,
            detail,
            latitude: mapCenter.lat,
            longitude: mapCenter.lon,
            time_start: board.anchor_date ? `${board.anchor_date}T00:00:00Z` : undefined,
          })
        }
      />
      <button
        className="ghost small danger"
        onClick={() => {
          if (window.confirm(`Delete the board "${board.title}"? This cannot be undone.`))
            mutations.remove.mutate(board.id, { onSuccess: () => onOpen(null) });
        }}
      >
        Delete board
      </button>
    </div>
  );
}

function LinkCard({
  link,
  from,
  to,
  busy,
  onStatus,
  onFocus,
}: {
  link: BoardLink;
  from: BoardNode | undefined;
  to: BoardNode | undefined;
  busy: boolean;
  onStatus(status: Status): void;
  onFocus(node: BoardNode | undefined): void;
}) {
  const quote = typeof link.evidence.quote === "string" ? link.evidence.quote : null;
  return (
    <li className={`card board-link is-${link.status}`}>
      <div className="card-head">
        <span className="badge">{RULE_LABELS[link.rule] ?? link.rule}</span>
        <span className="confidence" title="How strongly this ties the item to the story">
          <span className="confidence-track" aria-hidden>
            <span className="confidence-bar" style={{ width: `${Math.round(link.confidence * 100)}%` }} />
          </span>
          {Math.round(link.confidence * 100)}%
        </span>
      </div>
      <div className="board-link-ends small">
        <button className="link-end" onClick={() => onFocus(from)}>
          <span className="dot" style={{ background: from ? nodeColor(from) : undefined }} />
          {from?.label}
        </button>
        <span className="muted">→</span>
        <button className="link-end" onClick={() => onFocus(to)}>
          <span className="dot" style={{ background: to ? nodeColor(to) : undefined }} />
          {to?.label}
        </button>
      </div>
      <p className="small">{link.reason}</p>
      {quote && <blockquote className="small muted">“{quote}”</blockquote>}
      <div className="card-actions">
        <button className="small" disabled={busy || link.status === "accepted"} onClick={() => onStatus("accepted")}>
          Accept
        </button>
        <button className="small ghost" disabled={busy || link.status === "rejected"} onClick={() => onStatus("rejected")}>
          Reject
        </button>
        <span className="small muted">by {link.created_by}</span>
      </div>
    </li>
  );
}

function NodeGroups({
  board,
  selectedNodeId,
  expanding,
  onFocus,
  onExpand,
  onStatus,
  onLink,
}: {
  board: Board;
  selectedNodeId: number | null;
  expanding: number | null | undefined;
  onFocus(node: BoardNode): void;
  onExpand(node: BoardNode): void;
  onStatus(node: BoardNode, status: Status): void;
  onLink(node: BoardNode): void;
}) {
  const groups = new Map<string, BoardNode[]>();
  for (const n of board.nodes) {
    if (n.status === "rejected") continue;
    groups.set(n.kind, [...(groups.get(n.kind) ?? []), n]);
  }
  const order = ["article", "claim", "place", "actor", "event", "flight", "fire", "vessel", "note"];
  return (
    <div className="board-nodes">
      {order
        .filter((kind) => groups.has(kind))
        .map((kind) => (
          <details key={kind} open={kind !== "event" || groups.get(kind)!.length <= 12}>
            <summary>
              {KIND_LABELS[kind]} ({groups.get(kind)!.length})
            </summary>
            <ul className="node-list">
              {groups
                .get(kind)!
                .sort((a, b) => (b.time_start ?? "").localeCompare(a.time_start ?? ""))
                .map((n) => (
                  <li key={n.id} className={`node-row${n.id === selectedNodeId ? " is-selected" : ""}`}>
                    <button className="node-label" onClick={() => onFocus(n)} title={n.detail}>
                      <span className="dot" style={{ background: nodeColor(n) }} />
                      <span>{n.label}</span>
                      {n.time_start && <span className="muted small"> · {formatDate(n.time_start.slice(0, 10))}</span>}
                    </button>
                    <span className="node-actions">
                      {n.status === "suggested" && (
                        <button className="small ghost" title="Accept" onClick={() => onStatus(n, "accepted")}>
                          ✓
                        </button>
                      )}
                      <button className="small ghost" title="Reject" onClick={() => onStatus(n, "rejected")}>
                        ✕
                      </button>
                      <button className="small ghost" title="Link this to another item" onClick={() => onLink(n)}>
                        Link
                      </button>
                      {n.kind !== "article" && (
                        <button
                          className="small ghost"
                          title="Suggest more connections around this"
                          disabled={expanding === n.id}
                          onClick={() => onExpand(n)}
                        >
                          {expanding === n.id ? "…" : "Expand"}
                        </button>
                      )}
                    </span>
                  </li>
                ))}
            </ul>
          </details>
        ))}
    </div>
  );
}

function LinkForm({
  from,
  nodes,
  pending,
  error,
  onCancel,
  onSubmit,
}: {
  from: BoardNode;
  nodes: BoardNode[];
  pending: boolean;
  error: Error | null;
  onCancel(): void;
  onSubmit(to: number, reason: string): void;
}) {
  const [to, setTo] = useState<number | "">("");
  const [reason, setReason] = useState("");
  return (
    <form
      className="card board-link-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (to !== "" && reason.trim()) onSubmit(to, reason.trim());
      }}
    >
      <div className="small">
        Link <strong>{from.label}</strong> to
      </div>
      <select aria-label="Item to link to" value={to} onChange={(e) => setTo(e.target.value ? Number(e.target.value) : "")}>
        <option value="">Choose an item…</option>
        {nodes.map((n) => (
          <option key={n.id} value={n.id}>
            {KIND_LABELS[n.kind]}: {n.label}
          </option>
        ))}
      </select>
      <input
        aria-label="Why they are connected"
        placeholder="Why are they connected? (shown on the globe)"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <div className="button-row">
        <button type="submit" disabled={pending || to === "" || !reason.trim()}>
          Add link
        </button>
        <button type="button" className="ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
      {error && <p className="error small">{error.message}</p>}
    </form>
  );
}

function NoteForm({
  center,
  anchor,
  pending,
  onSubmit,
}: {
  center: { lon: number; lat: number };
  anchor: string | null;
  pending: boolean;
  onSubmit(label: string, detail: string): void;
}) {
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [detail, setDetail] = useState("");
  if (!open)
    return (
      <button className="small" onClick={() => setOpen(true)}>
        + Note at the map's centre
      </button>
    );
  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault();
        if (!label.trim()) return;
        onSubmit(label.trim(), detail.trim());
        setLabel("");
        setDetail("");
        setOpen(false);
      }}
    >
      <div className="small muted">
        At {center.lat.toFixed(3)}, {center.lon.toFixed(3)}
        {anchor ? `, dated ${formatDate(anchor)}` : ""}. Move the map to place it.
      </div>
      <input autoFocus aria-label="Note title" placeholder="What is here?" value={label} onChange={(e) => setLabel(e.target.value)} />
      <textarea aria-label="Note details" rows={3} placeholder="Details and source" value={detail} onChange={(e) => setDetail(e.target.value)} />
      <div className="button-row">
        <button type="submit" disabled={pending || !label.trim()}>
          Add note
        </button>
        <button type="button" className="ghost" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}
