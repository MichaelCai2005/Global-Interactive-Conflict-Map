import { useEffect, useState } from "react";
import { formatDate } from "../lib/dates";
import { type Board, type BoardLink, type BoardNode, siteOf, useImageSrc, useBoardMutations } from "./api";
import type { BoardSelection } from "./BoardCanvas";
import { KIND_LABELS, KIND_SINGULAR, RULE_LABELS, nodeColor } from "./style";

interface Props {
  board: Board;
  selection: NonNullable<BoardSelection>;
  mapCenter: { lon: number; lat: number };
  onSelect(selection: BoardSelection): void;
  /** Bring a card into view on the canvas (and the map, if it has a place). */
  onFocus(node: BoardNode): void;
  onShowOnMap(node: BoardNode): void;
}

/** The sidebar's view of the selected card or connection. */
export function ItemDetail(props: Props) {
  const { board, selection } = props;
  if (selection.type === "link") {
    const link = board.links.find((k) => k.id === selection.id);
    return link ? <LinkDetail key={link.id} {...props} link={link} /> : <Gone onClose={() => props.onSelect(null)} />;
  }
  const node = board.nodes.find((n) => n.id === selection.id);
  return node ? <NodeDetail key={node.id} {...props} node={node} /> : <Gone onClose={() => props.onSelect(null)} />;
}

function Gone({ onClose }: { onClose(): void }) {
  return (
    <div className="item-detail">
      <p className="muted small">That item is no longer on the board.</p>
      <button className="small" onClick={onClose}>
        Back to the board
      </button>
    </div>
  );
}

/** A text field that saves when you leave it or press Enter. */
function Editable({
  value,
  label,
  multiline,
  placeholder,
  onSave,
}: {
  value: string;
  label: string;
  multiline?: boolean;
  placeholder?: string;
  onSave(value: string): void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const save = () => {
    if (draft.trim() !== value.trim()) onSave(draft.trim());
  };
  const shared = {
    "aria-label": label,
    placeholder,
    value: draft,
    onBlur: save,
    onChange: (e: React.ChangeEvent<HTMLInputElement & HTMLTextAreaElement>) => setDraft(e.target.value),
  };
  return multiline ? (
    <textarea className="editable" rows={4} {...shared} />
  ) : (
    <input
      className="editable editable-title"
      {...shared}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        if (e.key === "Escape") setDraft(value);
      }}
    />
  );
}

function NodeDetail({ board, node, mapCenter, onSelect, onFocus, onShowOnMap }: Props & { node: BoardNode }) {
  const m = useBoardMutations(board.id);
  const [connecting, setConnecting] = useState(false);
  const [imageLink, setImageLink] = useState("");
  const save = (changes: Parameters<typeof m.updateNode.mutate>[0]["changes"]) =>
    m.updateNode.mutate({ nodeId: node.id, changes });
  const src = useImageSrc(node.image_url);
  const quote = node.quote;
  const own = node.kind === "note" || node.kind === "link";
  const error = m.updateNode.error ?? m.picture.error ?? m.deleteNode.error ?? m.expand.error ?? m.review.error ?? m.link.error;

  const byId = new Map(board.nodes.map((n) => [n.id, n]));
  const connections = board.links
    .filter((k) => k.status !== "rejected" && (k.from_node_id === node.id || k.to_node_id === node.id))
    .map((k) => ({ link: k, other: byId.get(k.from_node_id === node.id ? k.to_node_id : k.from_node_id)! }))
    .filter((c) => c.other && c.other.status !== "rejected")
    .sort((a, b) => Number(b.link.rule === "user") - Number(a.link.rule === "user") || b.link.confidence - a.link.confidence);

  return (
    <div className="item-detail">
      <div className="item-kind small">
        <span className="dot" style={{ background: nodeColor(node) }} />
        {KIND_SINGULAR[node.kind] ?? node.kind}
        {node.status === "suggested" && <span className="badge">Suggested</span>}
        <button className="ghost small item-close" onClick={() => onSelect(null)} aria-label="Close">
          ✕
        </button>
      </div>
      <Editable value={node.label} label="Title" onSave={(label) => label && save({ label })} />

      {src && (
        <a href={src} target="_blank" rel="noopener noreferrer" className="item-image" title="Open the picture in a new tab">
          <img src={src} alt={node.label} />
        </a>
      )}

      <div className="item-facts small">
        {node.time_start && <span>{formatDate(node.time_start.slice(0, 10))}</span>}
        {node.source_name && <span className="muted">{node.source_name}</span>}
        {node.created_by !== "user" && <span className="muted">added by {node.created_by === "ai" ? "Claude" : "the rules"}</span>}
      </div>

      <div className="button-row">
        {node.source_url && (
          <a className="button primary" href={node.source_url} target="_blank" rel="noopener noreferrer">
            Open {node.kind === "article" ? "article" : (siteOf(node.source_url) ?? "source")} ↗
          </a>
        )}
        {node.latitude !== null ? (
          <button onClick={() => onShowOnMap(node)}>Show on map</button>
        ) : (
          <button
            title="Pin this card where the map is centred now"
            onClick={() => save({ latitude: mapCenter.lat, longitude: mapCenter.lon })}
          >
            Pin to map centre
          </button>
        )}
      </div>

      {node.status === "suggested" && (
        <div className="item-review">
          <span className="small">Keep this on the board?</span>
          <button className="small" onClick={() => m.review.mutate({ status: "accepted", node_ids: [node.id] })}>
            Keep
          </button>
          <button className="small ghost" onClick={() => m.review.mutate({ status: "rejected", node_ids: [node.id] })}>
            Dismiss
          </button>
        </div>
      )}

      {quote && <blockquote className="small muted">“{quote}”</blockquote>}

      <Editable
        multiline
        value={node.detail}
        label="Notes"
        placeholder={own ? "What happened here, why it matters…" : "Your notes"}
        onSave={(detail) => save({ detail })}
      />

      {own && (
        <label className="field">
          <span>Link</span>
          <Editable
            value={node.source_url ?? ""}
            label="Link"
            placeholder="https://…"
            onSave={(url) => save({ source_url: url || null })}
          />
        </label>
      )}

      <div className="item-picture">
        <span className="small muted">{src ? "Picture" : "Add a picture of what happened here"}</span>
        <div className="button-row">
          <label className="button small file-button">
            {src ? "Replace" : "Upload"}
            <input
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) m.picture.mutate({ nodeId: node.id, file });
                e.target.value = "";
              }}
            />
          </label>
          {src && (
            <button className="small ghost" onClick={() => save({ image_url: null })}>
              Remove
            </button>
          )}
        </div>
        {!src && (
          <form
            className="inline-form"
            onSubmit={(e) => {
              e.preventDefault();
              if (imageLink.trim()) save({ image_url: imageLink.trim() });
              setImageLink("");
            }}
          >
            <input type="url" aria-label="Picture link" placeholder="…or a picture's link" value={imageLink} onChange={(e) => setImageLink(e.target.value)} />
            <button className="small" disabled={!imageLink.trim()}>
              Use
            </button>
          </form>
        )}
        {m.picture.isPending && <span className="small muted">Uploading…</span>}
      </div>

      <h3 className="section-title">Connected to ({connections.length})</h3>
      {connections.length === 0 && <p className="small muted">Nothing yet. Drag this card's dot onto another card, or:</p>}
      <ul className="item-connections">
        {connections.map(({ link, other }) => (
          <li key={link.id} className={`is-${link.status}`}>
            <button
              className="link-end"
              onClick={() => {
                onSelect({ type: "node", id: other.id });
                onFocus(other);
              }}
            >
              <span className="dot" style={{ background: nodeColor(other) }} />
              <span>{other.label}</span>
            </button>
            <button className="ghost small why" onClick={() => onSelect({ type: "link", id: link.id })} title="About this connection">
              {link.rule === "user" ? link.reason || "Your connection" : (RULE_LABELS[link.rule] ?? link.rule)}
              {link.status === "suggested" && " · suggested"}
            </button>
          </li>
        ))}
      </ul>

      {connecting ? (
        <ConnectForm
          from={node}
          nodes={board.nodes.filter((n) => n.id !== node.id && n.status !== "rejected")}
          pending={m.link.isPending}
          onCancel={() => setConnecting(false)}
          onSubmit={(to, reason) =>
            m.link.mutate({ from_node_id: node.id, to_node_id: to, reason }, { onSuccess: () => setConnecting(false) })
          }
        />
      ) : (
        <div className="button-row">
          <button className="small" onClick={() => setConnecting(true)}>
            Connect to…
          </button>
          {node.kind !== "article" && !own && (
            <button className="small" disabled={m.expand.isPending} onClick={() => m.expand.mutate(node.id)} title="Suggest more events, groups, flights and fires around this">
              {m.expand.isPending ? "Looking…" : "Find more around this"}
            </button>
          )}
          {node.latitude !== null && own && (
            <button className="small ghost" onClick={() => save({ latitude: null, longitude: null })}>
              Take off the map
            </button>
          )}
        </div>
      )}

      {error && <p className="error small">{error.message}</p>}

      <div className="item-footer">
        {own ? (
          <button
            className="ghost small danger"
            onClick={() => {
              if (window.confirm(`Delete "${node.label}" and its connections?`))
                m.deleteNode.mutate(node.id, { onSuccess: () => onSelect(null) });
            }}
          >
            Delete card
          </button>
        ) : (
          node.status !== "suggested" && (
            <button className="ghost small danger" onClick={() => m.review.mutate({ status: "rejected", node_ids: [node.id] }, { onSuccess: () => onSelect(null) })}>
              Take off the board
            </button>
          )
        )}
      </div>
    </div>
  );
}

function LinkDetail({ board, link, onSelect, onFocus }: Props & { link: BoardLink }) {
  const m = useBoardMutations(board.id);
  const from = board.nodes.find((n) => n.id === link.from_node_id);
  const to = board.nodes.find((n) => n.id === link.to_node_id);
  const quote = typeof link.evidence.quote === "string" ? link.evidence.quote : null;
  const own = link.rule === "user";
  const error = m.updateLink.error ?? m.deleteLink.error ?? m.review.error;
  const end = (n: BoardNode | undefined) =>
    n && (
      <button
        className="link-end"
        onClick={() => {
          onSelect({ type: "node", id: n.id });
          onFocus(n);
        }}
      >
        <span className="dot" style={{ background: nodeColor(n) }} />
        <span>{n.label}</span>
      </button>
    );
  return (
    <div className="item-detail">
      <div className="item-kind small">
        {own ? "Your connection" : (RULE_LABELS[link.rule] ?? link.rule)}
        {link.status === "suggested" && <span className="badge">Suggested</span>}
        <button className="ghost small item-close" onClick={() => onSelect(null)} aria-label="Close">
          ✕
        </button>
      </div>
      <div className="item-ends">
        {end(from)}
        <span className="muted small">connects to</span>
        {end(to)}
      </div>
      {own ? (
        <label className="field">
          <span>What connects them?</span>
          <Editable
            value={link.reason}
            label="What connects them"
            placeholder="e.g. same supplier, retaliation for…"
            onSave={(reason) => m.updateLink.mutate({ linkId: link.id, changes: { reason } })}
          />
        </label>
      ) : (
        <>
          <p className="small">{link.reason}</p>
          {quote && <blockquote className="small muted">“{quote}”</blockquote>}
          <p className="small muted">
            Strength {Math.round(link.confidence * 100)}%: how closely this ties to the story, from distance, time and how well
            the names matched.
          </p>
        </>
      )}
      {link.status === "suggested" && (
        <div className="item-review">
          <span className="small">Keep this connection?</span>
          <button className="small" onClick={() => m.review.mutate({ status: "accepted", link_ids: [link.id] })}>
            Keep
          </button>
          <button className="small ghost" onClick={() => m.review.mutate({ status: "rejected", link_ids: [link.id] }, { onSuccess: () => onSelect(null) })}>
            Dismiss
          </button>
        </div>
      )}
      {error && <p className="error small">{error.message}</p>}
      <div className="item-footer">
        {own ? (
          <button className="ghost small danger" onClick={() => m.deleteLink.mutate(link.id, { onSuccess: () => onSelect(null) })}>
            Delete connection
          </button>
        ) : (
          link.status === "accepted" && (
            <button className="ghost small danger" onClick={() => m.review.mutate({ status: "rejected", link_ids: [link.id] }, { onSuccess: () => onSelect(null) })}>
              Remove connection
            </button>
          )
        )}
      </div>
    </div>
  );
}

function ConnectForm({
  from,
  nodes,
  pending,
  onCancel,
  onSubmit,
}: {
  from: BoardNode;
  nodes: BoardNode[];
  pending: boolean;
  onCancel(): void;
  onSubmit(to: number, reason: string): void;
}) {
  const [to, setTo] = useState<number | "">("");
  const [reason, setReason] = useState("");
  const kinds = [...new Set(nodes.map((n) => n.kind))];
  return (
    <form
      className="card connect-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (to !== "") onSubmit(to, reason.trim());
      }}
    >
      <div className="small">
        Connect <strong>{from.label}</strong> to
      </div>
      <select aria-label="Card to connect to" value={to} onChange={(e) => setTo(e.target.value ? Number(e.target.value) : "")}>
        <option value="">Choose a card…</option>
        {kinds.map((kind) => (
          <optgroup key={kind} label={KIND_LABELS[kind] ?? kind}>
            {nodes
              .filter((n) => n.kind === kind)
              .map((n) => (
                <option key={n.id} value={n.id}>
                  {n.label}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
      <input aria-label="What connects them" placeholder="What connects them? (optional)" value={reason} onChange={(e) => setReason(e.target.value)} />
      <div className="button-row">
        <button type="submit" disabled={pending || to === ""}>
          Connect
        </button>
        <button type="button" className="ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
