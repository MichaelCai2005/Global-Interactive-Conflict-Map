import { useMemo, useState } from "react";
import { type DateWindow, addDays, formatDate } from "../lib/dates";
import { plural } from "../lib/format";
import { type Board, type BoardLink, type BoardNode, type Status, useBoard, useBoardMutations, useBoards } from "./api";
import type { BoardSelection } from "./BoardCanvas";
import { ItemDetail } from "./ItemDetail";
import "./board.css";
import { KIND_LABELS, RULE_LABELS, nodeColor } from "./style";

interface Props {
  boardId: number | null;
  selection: BoardSelection;
  mapCenter: { lon: number; lat: number };
  onOpen(boardId: number | null): void;
  onSelect(selection: BoardSelection): void;
  /** Bring a card into view: on the canvas, and on the map if it has a place. */
  onFocus(node: BoardNode): void;
  onShowOnMap(node: BoardNode): void;
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
        Start from a news article, a topic or a blank board. The board lays out the places, groups
        and events the story connects to, each with its reason and source. Arrange it like a mood
        board: add notes, pictures and links, and draw your own connections.
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
              {plural(b.nodes, "card")}, {b.accepted} kept
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
  selection,
  mapCenter,
  onOpen,
  onSelect,
  onFocus,
  onShowOnMap,
  onWindow,
}: Props & { boardId: number }) {
  const { data: board, isLoading, error } = useBoard(boardId);
  const mutations = useBoardMutations(boardId);
  const [filter, setFilter] = useState<ReviewFilter>("suggested");

  const nodes = useMemo(() => new Map(board?.nodes.map((n) => [n.id, n]) ?? []), [board]);
  if (error) return <div className="panel-body error">Could not load the board: {error.message}</div>;
  if (isLoading || !board) return <div className="panel-body muted">Loading…</div>;

  if (selection)
    return (
      <div className="panel-body board-panel">
        <button className="ghost small back" onClick={() => onSelect(null)}>
          ← {board.title}
        </button>
        <ItemDetail
          board={board}
          selection={selection}
          mapCenter={mapCenter}
          onSelect={onSelect}
          onFocus={onFocus}
          onShowOnMap={onShowOnMap}
        />
      </div>
    );

  const counts = {
    suggested: board.links.filter((k) => k.status === "suggested").length,
    accepted: board.links.filter((k) => k.status === "accepted").length,
    rejected: board.links.filter((k) => k.status === "rejected").length,
  };
  const links = board.links
    .filter((k) => filter === "all" || k.status === filter)
    .sort((a, b) => b.confidence - a.confidence);
  const strong = board.links.filter((k) => k.status === "suggested" && k.confidence >= 0.8);
  const shown = board.nodes.filter((n) => n.status !== "rejected").length;
  const select = (node: BoardNode | undefined) => {
    if (!node) return;
    onSelect({ type: "node", id: node.id });
    onFocus(node);
  };

  return (
    <div className="panel-body board-panel">
      <button className="ghost small back" onClick={() => onOpen(null)}>
        ← All boards
      </button>
      <h2 className="board-title">{board.title}</h2>
      <p className="small muted">
        {board.anchor_date ? formatDate(board.anchor_date) : "No date"} · {plural(shown, "card")}
        {board.extractor ? ` · read by ${board.extractor}` : ""}
        {board.source_url && (
          <>
            {" · "}
            <a href={board.source_url} target="_blank" rel="noopener noreferrer">
              source ↗
            </a>
          </>
        )}
      </p>
      {board.notes && <p className="notes small board-notes">{board.notes}</p>}
      <p className="small muted">
        Click a card to see it here, with its source, pictures and connections. Add notes, pictures, links and more
        articles from the board's toolbar.
      </p>
      {storyWindow(board) && (
        <div className="button-row">
          <button className="small ghost" onClick={() => onWindow(storyWindow(board)!)}>
            Show its time on the timeline
          </button>
        </div>
      )}

      <h3 className="section-title">Suggestions to review</h3>
      <div className="segmented small" role="tablist" aria-label="Which links">
        {(["suggested", "accepted", "rejected", "all"] as const).map((f) => (
          <button key={f} role="tab" aria-selected={filter === f} className={filter === f ? "is-on" : ""} onClick={() => setFilter(f)}>
            {f === "suggested"
              ? `To review (${counts.suggested})`
              : f === "all"
                ? "All"
                : `${f === "accepted" ? "Kept" : "Dismissed"} (${counts[f]})`}
          </button>
        ))}
      </div>
      {filter === "suggested" && strong.length > 1 && (
        <button
          className="small"
          disabled={mutations.review.isPending}
          onClick={() => mutations.review.mutate({ status: "accepted", link_ids: strong.map((k) => k.id) })}
        >
          Keep the {strong.length} links at 80% or more
        </button>
      )}
      {links.length === 0 && <p className="empty small">Nothing here.</p>}
      <ul className="cards board-links">
        {links.slice(0, 40).map((k) => (
          <LinkCard
            key={k.id}
            link={k}
            from={nodes.get(k.from_node_id)}
            to={nodes.get(k.to_node_id)}
            busy={mutations.review.isPending}
            onStatus={(s) => mutations.review.mutate({ status: s, link_ids: [k.id] })}
            onFocus={select}
            onOpen={() => onSelect({ type: "link", id: k.id })}
          />
        ))}
      </ul>
      {links.length > 40 && <p className="small muted">And {links.length - 40} more; keep or dismiss some to see them.</p>}

      <h3 className="section-title">All cards</h3>
      <NodeGroups board={board} onOpen={select} />
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
  onOpen,
}: {
  link: BoardLink;
  from: BoardNode | undefined;
  to: BoardNode | undefined;
  busy: boolean;
  onStatus(status: Status): void;
  onFocus(node: BoardNode | undefined): void;
  onOpen(): void;
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
      <button className="link-reason small" onClick={onOpen}>
        {link.reason || "Your connection"}
      </button>
      {quote && <blockquote className="small muted">“{quote}”</blockquote>}
      <div className="card-actions">
        <button className="small" disabled={busy || link.status === "accepted"} onClick={() => onStatus("accepted")}>
          Keep
        </button>
        <button className="small ghost" disabled={busy || link.status === "rejected"} onClick={() => onStatus("rejected")}>
          Dismiss
        </button>
        <span className="small muted">by {link.created_by}</span>
      </div>
    </li>
  );
}

function NodeGroups({ board, onOpen }: { board: Board; onOpen(node: BoardNode): void }) {
  const groups = new Map<string, BoardNode[]>();
  for (const n of board.nodes) {
    if (n.status === "rejected") continue;
    groups.set(n.kind, [...(groups.get(n.kind) ?? []), n]);
  }
  const order = ["article", "link", "note", "claim", "place", "actor", "event", "flight", "fire", "vessel"];
  return (
    <div className="board-nodes">
      {order
        .filter((kind) => groups.has(kind))
        .map((kind) => (
          <details key={kind} open={groups.get(kind)!.length <= 12}>
            <summary>
              {KIND_LABELS[kind]} ({groups.get(kind)!.length})
            </summary>
            <ul className="node-list">
              {groups
                .get(kind)!
                .sort((a, b) => (b.time_start ?? "").localeCompare(a.time_start ?? ""))
                .map((n) => (
                  <li key={n.id} className={`node-row is-${n.status}`}>
                    <button className="node-label" onClick={() => onOpen(n)} title={n.detail}>
                      <span className="dot" style={{ background: nodeColor(n) }} />
                      <span>{n.label}</span>
                      {n.time_start && <span className="muted small"> · {formatDate(n.time_start.slice(0, 10))}</span>}
                    </button>
                    {n.source_url && (
                      <a className="small" href={n.source_url} target="_blank" rel="noopener noreferrer" title="Open the source in a new tab">
                        ↗
                      </a>
                    )}
                  </li>
                ))}
            </ul>
          </details>
        ))}
    </div>
  );
}
