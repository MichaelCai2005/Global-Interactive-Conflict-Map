import { useState } from "react";
import { siteOf, useBoardMutations } from "./api";
import type { BoardSelection } from "./BoardCanvas";
import type { Point } from "./layout";

export type AddMode = "note" | "picture" | "link" | "article";

const MODES: [AddMode, string][] = [
  ["note", "Note"],
  ["picture", "Picture"],
  ["link", "Link"],
  ["article", "Article"],
];

/** The panel for adding a card from the board's toolbar. New cards land at `at`. */
export function AddCard({
  boardId,
  mode,
  at,
  onMode,
  onClose,
  onAdded,
}: {
  boardId: number;
  mode: AddMode;
  at: Point;
  onMode(mode: AddMode): void;
  onClose(): void;
  onAdded(selection: BoardSelection): void;
}) {
  const { card, article } = useBoardMutations(boardId);
  const [label, setLabel] = useState("");
  const [detail, setDetail] = useState("");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [paste, setPaste] = useState(false);
  const pending = card.isPending || article.isPending;
  const error = card.error ?? article.error;
  const spot = { board_x: Math.round(at.x), board_y: Math.round(at.y) };
  const added = (n: { id: number }) => onAdded({ type: "node", id: n.id });

  const ready =
    mode === "note"
      ? Boolean(label.trim())
      : mode === "picture"
        ? Boolean(file || url.trim())
        : mode === "link"
          ? /^https?:\/\/\S+/i.test(url.trim())
          : Boolean(url.trim() || (paste && text.trim()));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!ready) return;
    const trimmed = url.trim();
    if (mode === "note") {
      card.mutate({ kind: "note", label: label.trim(), detail: detail.trim(), ...spot }, { onSuccess: added });
    } else if (mode === "picture") {
      card.mutate(
        {
          kind: "note",
          label: label.trim() || file?.name.replace(/\.[^.]+$/, "") || "Picture",
          detail: detail.trim(),
          file: file ?? undefined,
          image_url: file ? undefined : trimmed,
          ...spot,
        },
        { onSuccess: added },
      );
    } else if (mode === "link") {
      card.mutate(
        { kind: "link", label: label.trim() || siteOf(trimmed) || trimmed, detail: detail.trim(), source_url: trimmed, ...spot },
        { onSuccess: added },
      );
    } else {
      article.mutate(
        { url: trimmed || undefined, text: paste ? text.trim() : undefined, title: label.trim() || undefined, ...spot },
        {
          onSuccess: (board) => {
            // The new article is the newest article card.
            const newest = board.nodes.filter((n) => n.kind === "article").sort((a, b) => b.id - a.id)[0];
            onAdded(newest ? { type: "node", id: newest.id } : null);
          },
        },
      );
    }
  };

  return (
    <form className="board-add" onSubmit={submit} aria-label="Add to the board">
      <div className="board-add-head">
        <div className="segmented small" role="tablist" aria-label="What to add">
          {MODES.map(([value, name]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={mode === value}
              className={mode === value ? "is-on" : ""}
              onClick={() => onMode(value)}
            >
              {name}
            </button>
          ))}
        </div>
        <button type="button" className="ghost small" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>

      {mode === "note" && (
        <>
          <input autoFocus aria-label="Note" placeholder="What's the idea?" value={label} onChange={(e) => setLabel(e.target.value)} />
          <textarea aria-label="Details" rows={3} placeholder="Details (optional)" value={detail} onChange={(e) => setDetail(e.target.value)} />
        </>
      )}

      {mode === "picture" && (
        <>
          <label className="field">
            <span>Upload a picture (PNG, JPEG, GIF, WebP, up to 5 MB)</span>
            <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
          {!file && (
            <input type="url" aria-label="Picture link" placeholder="…or paste a picture's link" value={url} onChange={(e) => setUrl(e.target.value)} />
          )}
          <input aria-label="Caption" placeholder="Caption: what does it show?" value={label} onChange={(e) => setLabel(e.target.value)} />
          <textarea aria-label="Details" rows={2} placeholder="What happened here (optional)" value={detail} onChange={(e) => setDetail(e.target.value)} />
        </>
      )}

      {mode === "link" && (
        <>
          <input autoFocus type="url" aria-label="Link" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} />
          <input aria-label="Title" placeholder="Title (optional)" value={label} onChange={(e) => setLabel(e.target.value)} />
          <textarea aria-label="Why it matters" rows={2} placeholder="Why it matters (optional)" value={detail} onChange={(e) => setDetail(e.target.value)} />
        </>
      )}

      {mode === "article" && (
        <>
          <p className="small muted">
            The article is read, and the places, groups and events it names are linked to the board's cards.
          </p>
          <input autoFocus type="url" aria-label="Article link" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} />
          <label className="check small">
            <input type="checkbox" checked={paste} onChange={(e) => setPaste(e.target.checked)} /> Paste the text instead (for
            paywalled sites)
          </label>
          {paste && (
            <textarea aria-label="Article text" rows={5} placeholder="Paste the article's text" value={text} onChange={(e) => setText(e.target.value)} />
          )}
        </>
      )}

      <button type="submit" className="primary" disabled={!ready || pending}>
        {pending ? (mode === "article" ? "Reading and linking… (up to a minute)" : "Adding…") : "Add to board"}
      </button>
      {error && <p className="error small">{error.message}</p>}
    </form>
  );
}
