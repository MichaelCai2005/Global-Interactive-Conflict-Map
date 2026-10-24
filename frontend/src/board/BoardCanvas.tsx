import { type Ref, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from "react";
import { formatDate } from "../lib/dates";
import { type Board, type BoardLink, type BoardNode, siteOf, useImageSrc, useBoardMutations } from "./api";
import { AddCard, type AddMode } from "./AddCard";
import { CARD_WIDTH, type Point, cardHeight, freeSpot, layoutBoard } from "./layout";
import { KIND_SINGULAR, RULE_LABELS, nodeColor } from "./style";
import "./canvas.css";

// The board as a mood board: cards you can drag about, lines between them, and anything
// dropped on it (pictures, links) becomes a card. The sidebar shows the selected card.

export type BoardSelection = { type: "node" | "link"; id: number } | null;

export interface CanvasHandle {
  /** Scroll the canvas so a card is in the middle. */
  centerOn(nodeId: number): void;
}

interface Props {
  ref?: Ref<CanvasHandle>;
  board: Board;
  selection: BoardSelection;
  onSelect(selection: BoardSelection): void;
}

interface View {
  x: number;
  y: number;
  k: number;
}

type Drag =
  | { mode: "pan"; sx: number; sy: number; view: View; moved: boolean }
  | { mode: "card"; id: number; sx: number; sy: number; origin: Point; moved: boolean; at?: Point }
  | { mode: "connect"; from: number };

const MIN_ZOOM = 0.2;
const MAX_ZOOM = 2;
const READABLE_ZOOM = 0.75;
const IMAGE_FILE = /^image\/(png|jpeg|gif|webp)$/;
const IMAGE_LINK = /\.(png|jpe?g|gif|webp)(\?.*)?$/i;

export function BoardCanvas({ ref, board, selection, onSelect }: Props) {
  const mutations = useBoardMutations(board.id);
  const box = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<View>({ x: 40, y: 40, k: 0.85 });
  const viewRef = useRef(view);
  viewRef.current = view;
  const drag = useRef<Drag | null>(null);
  const [dragged, setDragged] = useState<{ id: number; at: Point } | null>(null);
  const [connecting, setConnecting] = useState<{ from: number; to: Point } | null>(null);
  const [showSuggested, setShowSuggested] = useState(true);
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState<{ mode: AddMode; at: Point } | null>(null);
  const [quick, setQuick] = useState<Point | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  // Cards report their rendered height, so the layout and the lines fit them exactly.
  const [heights, setHeights] = useState<Map<number, number>>(() => new Map());
  const heightOf = (n: BoardNode) => heights.get(n.id) ?? cardHeight(n);
  const measured = (id: number, h: number) =>
    setHeights((old) => (Math.abs((old.get(id) ?? 0) - h) < 1 ? old : new Map(old).set(id, h)));

  const shown = (n: BoardNode) => n.status !== "rejected" && (showSuggested || n.status === "accepted");
  const positions = useMemo(() => layoutBoard(board, shown, heightOf), [board, showSuggested, heights]);
  const at = (id: number) => (dragged?.id === id ? dragged.at : positions.get(id));
  const nodes = board.nodes.filter(shown);
  const nodeById = useMemo(() => new Map(board.nodes.map((n) => [n.id, n])), [board]);
  const links = board.links.filter(
    (k) => k.status !== "rejected" && (showSuggested || k.status === "accepted") && positions.has(k.from_node_id) && positions.has(k.to_node_id),
  );

  // Cards linked to the selected one stay bright; the rest fade back.
  const near = useMemo(() => {
    if (selection?.type !== "node") return null;
    const ids = new Set([selection.id]);
    for (const k of links) {
      if (k.from_node_id === selection.id) ids.add(k.to_node_id);
      if (k.to_node_id === selection.id) ids.add(k.from_node_id);
    }
    return ids;
  }, [selection, links]);
  const query = search.trim().toLowerCase();
  const matches = query ? nodes.filter((n) => n.label.toLowerCase().includes(query)) : [];

  const toWorld = (clientX: number, clientY: number): Point => {
    const rect = box.current!.getBoundingClientRect();
    const v = viewRef.current;
    return { x: (clientX - rect.left - v.x) / v.k, y: (clientY - rect.top - v.y) / v.k };
  };
  const middle = (): Point => {
    const el = box.current;
    if (!el) return { x: 0, y: 0 };
    const rect = el.getBoundingClientRect();
    return toWorld(rect.left + rect.width / 2 - CARD_WIDTH / 2, rect.top + rect.height / 2 - 60);
  };

  const centerOn = (id: number) => {
    const p = positions.get(id);
    const el = box.current;
    if (!p || !el) return;
    const node = nodeById.get(id);
    const k = Math.max(viewRef.current.k, 0.7);
    const h = node ? heightOf(node) : 100;
    setView({ k, x: el.clientWidth / 2 - (p.x + CARD_WIDTH / 2) * k, y: el.clientHeight / 2 - (p.y + h / 2) * k });
  };
  useImperativeHandle(ref, () => ({ centerOn }));

  /** Show the whole board; when opening one, no smaller than readable, from its top left. */
  const fit = (opening = false) => {
    const el = box.current;
    if (!el || positions.size === 0) return;
    let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
    for (const [id, p] of positions) {
      const n = nodeById.get(id)!;
      x0 = Math.min(x0, p.x);
      y0 = Math.min(y0, p.y);
      x1 = Math.max(x1, p.x + CARD_WIDTH);
      y1 = Math.max(y1, p.y + heightOf(n));
    }
    const pad = 40;
    const top = 64; // below the toolbar
    const whole = Math.min(1, (el.clientWidth - pad * 2) / (x1 - x0), (el.clientHeight - top - pad) / (y1 - y0));
    const k = Math.max(opening ? READABLE_ZOOM : MIN_ZOOM, whole);
    const spareX = el.clientWidth - (x1 - x0) * k;
    const spareY = el.clientHeight - top - pad - (y1 - y0) * k;
    setView({
      k,
      x: (spareX > 0 ? spareX / 2 : pad) - x0 * k,
      y: top + Math.max(0, spareY / 2) - y0 * k,
    });
  };

  // Each board opens fitted to the window.
  const fitted = useRef<number | null>(null);
  useEffect(() => {
    if (fitted.current !== board.id && positions.size > 0) {
      fitted.current = board.id;
      fit(true);
    }
  });

  const zoomBy = (factor: number, clientX?: number, clientY?: number) => {
    const el = box.current!;
    const rect = el.getBoundingClientRect();
    const sx = clientX === undefined ? rect.width / 2 : clientX - rect.left;
    const sy = clientY === undefined ? rect.height / 2 : clientY - rect.top;
    setView((v) => {
      const k = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, v.k * factor));
      return { k, x: sx - ((sx - v.x) / v.k) * k, y: sy - ((sy - v.y) / v.k) * k };
    });
  };

  // React's wheel listener is passive, so the page would scroll too; this one is not.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if ((e.target as HTMLElement).closest(".board-toolbar, .board-add")) return;
      e.preventDefault();
      zoomBy(Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.0015)), e.clientX, e.clientY);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    const target = e.target as HTMLElement;
    if (target.closest("a, button, input, textarea, select, .board-toolbar, .board-add, .board-quick")) return;
    // Lines are picked here, not on click: the pointer capture below would swallow it.
    const line = target.closest<SVGElement | HTMLElement>("[data-link-id]");
    if (line) {
      onSelect({ type: "link", id: Number(line.dataset.linkId) });
      return;
    }
    const handle = target.closest<HTMLElement>(".bcard-handle");
    const card = target.closest<HTMLElement>("[data-node-id]");
    box.current!.setPointerCapture(e.pointerId);
    if (handle && card) {
      const from = Number(card.dataset.nodeId);
      drag.current = { mode: "connect", from };
      setConnecting({ from, to: toWorld(e.clientX, e.clientY) });
    } else if (card) {
      const id = Number(card.dataset.nodeId);
      drag.current = { mode: "card", id, sx: e.clientX, sy: e.clientY, origin: positions.get(id)!, moved: false };
    } else {
      drag.current = { mode: "pan", sx: e.clientX, sy: e.clientY, view: viewRef.current, moved: false };
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    if (d.mode === "connect") {
      setConnecting({ from: d.from, to: toWorld(e.clientX, e.clientY) });
      return;
    }
    const dx = e.clientX - d.sx;
    const dy = e.clientY - d.sy;
    if (!d.moved && Math.hypot(dx, dy) < 4) return;
    d.moved = true;
    if (d.mode === "pan") setView({ ...d.view, x: d.view.x + dx, y: d.view.y + dy });
    else {
      const k = viewRef.current.k;
      // Kept on the drag too: the drop can come before React renders the last move.
      d.at = { x: d.origin.x + dx / k, y: d.origin.y + dy / k };
      setDragged({ id: d.id, at: d.at });
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (d.mode === "connect") {
      setConnecting(null);
      const under = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>("[data-node-id]");
      const to = under ? Number(under.dataset.nodeId) : null;
      if (to === null || to === d.from) return;
      const exists = board.links.find(
        (k) => k.rule === "user" && ((k.from_node_id === d.from && k.to_node_id === to) || (k.from_node_id === to && k.to_node_id === d.from)),
      );
      if (exists) {
        onSelect({ type: "link", id: exists.id });
        return;
      }
      mutations.link.mutate(
        { from_node_id: d.from, to_node_id: to },
        { onSuccess: (link) => onSelect({ type: "link", id: link.id }), onError: (err) => setProblem(err.message) },
      );
    } else if (d.mode === "card") {
      if (!d.moved) onSelect({ type: "node", id: d.id });
      else if (d.at) {
        // Cards still placed by the layout are saved where they are too, or they would
        // follow the moved card around (they sit relative to the card they hang off).
        const unsaved = board.nodes.filter((n) => n.id !== d.id && n.board_x === null && positions.has(n.id));
        mutations.layout.mutate(
          [
            { id: d.id, x: Math.round(d.at.x), y: Math.round(d.at.y) },
            ...unsaved.map((n) => ({ id: n.id, x: Math.round(positions.get(n.id)!.x), y: Math.round(positions.get(n.id)!.y) })),
          ],
          { onSettled: () => setDragged(null) },
        );
        return;
      }
      setDragged(null);
    } else if (!d.moved) {
      onSelect(null);
      setQuick(null);
    }
  };

  const onDoubleClick = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest("[data-node-id], .board-toolbar, .board-add, .board-quick, .link-hit")) return;
    setQuick(toWorld(e.clientX, e.clientY));
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const spot = toWorld(e.clientX, e.clientY);
    const file = [...e.dataTransfer.files].find((f) => IMAGE_FILE.test(f.type));
    if (file) {
      mutations.card.mutate(
        { kind: "note", label: file.name.replace(/\.[^.]+$/, "") || "Picture", file, board_x: spot.x, board_y: spot.y },
        { onSuccess: (n) => onSelect({ type: "node", id: n.id }), onError: (err) => setProblem(err.message) },
      );
      return;
    }
    if (e.dataTransfer.files.length) {
      setProblem("Only PNG, JPEG, GIF and WebP pictures can be dropped here");
      return;
    }
    const url = (e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text/plain")).split("\n")[0]!.trim();
    if (!/^https?:\/\//i.test(url)) return;
    const card = IMAGE_LINK.test(url)
      ? { kind: "note" as const, label: "Picture", image_url: url }
      : { kind: "link" as const, label: siteOf(url) ?? url, source_url: url };
    mutations.card.mutate(
      { ...card, board_x: spot.x, board_y: spot.y },
      { onSuccess: (n) => onSelect({ type: "node", id: n.id }), onError: (err) => setProblem(err.message) },
    );
  };

  const tidy = () => {
    if (!window.confirm("Lay every card out again? Cards you moved will move too.")) return;
    const fresh = layoutBoard({ ...board, nodes: board.nodes.map((n) => ({ ...n, board_x: null, board_y: null })) }, shown, heightOf);
    mutations.layout.mutate([...fresh].map(([id, p]) => ({ id, x: Math.round(p.x), y: Math.round(p.y) })), {
      onSuccess: () => setTimeout(() => fit(), 0),
    });
  };

  const openAdd = (mode: AddMode) => setAdding({ mode, at: freeSpot(middle(), positions.values()) });

  return (
    <div
      ref={box}
      className={`board-canvas${drag.current?.mode === "pan" ? " is-panning" : ""}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => {
        drag.current = null;
        setDragged(null);
        setConnecting(null);
      }}
      onDoubleClick={onDoubleClick}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
      aria-label="Board canvas"
    >
      <div className="board-world" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})` }}>
        <Lines
          links={links}
          nodes={nodeById}
          at={at}
          heightOf={heightOf}
          selection={selection}
          near={near}
          connecting={connecting && { from: at(connecting.from)!, fromNode: nodeById.get(connecting.from)!, to: connecting.to }}
        />
        {nodes.map((n) => {
          const p = at(n.id);
          if (!p) return null;
          const faded = (near && !near.has(n.id)) || (query && !matches.includes(n));
          return (
            <Card
              key={n.id}
              node={n}
              at={p}
              selected={selection?.type === "node" && selection.id === n.id}
              faded={Boolean(faded)}
              lifted={dragged?.id === n.id}
              busy={mutations.review.isPending}
              onReview={(status) => mutations.review.mutate({ status, node_ids: [n.id] })}
              onHeight={(h) => measured(n.id, h)}
            />
          );
        })}
        {quick && (
          <QuickNote
            at={quick}
            pending={mutations.card.isPending}
            onCancel={() => setQuick(null)}
            onSubmit={(label) =>
              mutations.card.mutate(
                { kind: "note", label, board_x: quick.x, board_y: quick.y },
                {
                  onSuccess: (n) => {
                    setQuick(null);
                    onSelect({ type: "node", id: n.id });
                  },
                  onError: (err) => setProblem(err.message),
                },
              )
            }
          />
        )}
      </div>

      <div className="board-toolbar" role="toolbar" aria-label="Board tools">
        <div className="tool-group">
          <button onClick={() => openAdd("note")} title="A note or idea">
            + Note
          </button>
          <button onClick={() => openAdd("picture")} title="A picture, uploaded or from a link">
            + Picture
          </button>
          <button onClick={() => openAdd("link")} title="A link to any web page">
            + Link
          </button>
          <button onClick={() => openAdd("article")} title="Read a news article and link what it names">
            + Article
          </button>
        </div>
        <div className="tool-group">
          <input
            type="search"
            className="board-search"
            placeholder="Find a card…"
            aria-label="Find a card"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && matches[0]) {
                centerOn(matches[0].id);
                onSelect({ type: "node", id: matches[0].id });
              }
              if (e.key === "Escape") setSearch("");
            }}
          />
          {query && <span className="small muted">{matches.length} found</span>}
        </div>
        <div className="tool-group">
          <label className="check small" title="Show what the rules suggest, to keep or dismiss">
            <input type="checkbox" checked={showSuggested} onChange={(e) => setShowSuggested(e.target.checked)} /> Suggestions
          </label>
          <button onClick={() => zoomBy(1 / 1.25)} aria-label="Zoom out">
            −
          </button>
          <button onClick={() => zoomBy(1.25)} aria-label="Zoom in">
            +
          </button>
          <button onClick={() => fit()} title="Show the whole board">
            Fit
          </button>
          <button onClick={tidy} title="Lay the cards out again" disabled={mutations.layout.isPending}>
            Tidy up
          </button>
        </div>
      </div>

      {adding && (
        <AddCard
          boardId={board.id}
          mode={adding.mode}
          at={adding.at}
          onMode={(mode) => setAdding({ ...adding, mode })}
          onClose={() => setAdding(null)}
          onAdded={(selected) => {
            setAdding(null);
            if (selected) {
              onSelect(selected);
              if (selected.type === "node") setTimeout(() => centerOn(selected.id), 0);
            }
          }}
        />
      )}

      {problem && (
        <div className="board-problem error small" role="alert">
          {problem}
          <button className="ghost small" onClick={() => setProblem(null)} aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}
      {nodes.length === 0 ? (
        <div className="board-empty">
          <p>This board is empty.</p>
          <p className="small muted">Add a note, a picture, a link or an article from the toolbar, or drop pictures and links here.</p>
        </div>
      ) : (
        <div className="board-hint small muted">
          Drag cards to arrange them · drag a card's <span className="hint-dot" aria-hidden /> onto another to connect them ·
          double-click for a note · drop pictures or links here
        </div>
      )}
    </div>
  );
}

function Card({
  node,
  at,
  selected,
  faded,
  lifted,
  busy,
  onReview,
  onHeight,
}: {
  node: BoardNode;
  at: Point;
  selected: boolean;
  faded: boolean;
  lifted: boolean;
  busy: boolean;
  onReview(status: "accepted" | "rejected"): void;
  onHeight(height: number): void;
}) {
  const el = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (el.current) onHeight(el.current.offsetHeight);
  });
  const src = useImageSrc(node.image_url);
  const site = siteOf(node.source_url) ?? node.source_name;
  const date = node.time_start ? formatDate(node.time_start.slice(0, 10)) : null;
  const classes = ["bcard", `is-${node.status}`, selected && "is-selected", faded && "is-faded", lifted && "is-lifted"];
  return (
    <div
      ref={el}
      className={classes.filter(Boolean).join(" ")}
      data-node-id={node.id}
      style={{ transform: `translate(${at.x}px, ${at.y}px)`, width: CARD_WIDTH, borderTopColor: nodeColor(node) }}
      aria-selected={selected}
    >
      {src && <img className="bcard-image" src={src} alt="" draggable={false} />}
      <div className="bcard-body">
        <div className="bcard-kind">
          <span className="dot" style={{ background: nodeColor(node) }} />
          {KIND_SINGULAR[node.kind] ?? node.kind}
          {date && <span className="muted"> · {date}</span>}
          {node.latitude !== null && (
            <span className="bcard-pin" title="On the map">
              ◉
            </span>
          )}
        </div>
        <div className="bcard-title">{node.label}</div>
        {node.source_url && (
          <a className="bcard-source" href={node.source_url} target="_blank" rel="noopener noreferrer" title={node.source_url}>
            {site ?? "Open"} ↗
          </a>
        )}
      </div>
      {node.status === "suggested" && (
        <div className="bcard-review">
          <button className="small" disabled={busy} onClick={() => onReview("accepted")} title="Keep it on the board">
            Keep
          </button>
          <button className="small ghost" disabled={busy} onClick={() => onReview("rejected")} title="Take it off the board">
            Dismiss
          </button>
        </div>
      )}
      <span className="bcard-handle" title="Drag onto another card to connect them" />
    </div>
  );
}

// --- Lines between cards -------------------------------------------------------------

interface Anchor {
  x: number;
  y: number;
  nx: number;
  ny: number;
}

/** Where the line from a card's centre towards `toward` leaves the card, and which way. */
function edge(p: Point, height: number, toward: Point): Anchor {
  const w = CARD_WIDTH / 2;
  const h = height / 2;
  const cx = p.x + w;
  const cy = p.y + h;
  const dx = toward.x - cx;
  const dy = toward.y - cy;
  if (Math.abs(dx) * h > Math.abs(dy) * w) {
    const s = Math.sign(dx) || 1;
    return { x: cx + s * w, y: cy + (dy * w) / Math.max(1, Math.abs(dx)), nx: s, ny: 0 };
  }
  const s = Math.sign(dy) || 1;
  return { x: cx + (dx * h) / Math.max(1, Math.abs(dy)), y: cy + s * h, nx: 0, ny: s };
}

function centre(p: Point, height: number): Point {
  return { x: p.x + CARD_WIDTH / 2, y: p.y + height / 2 };
}

function curve(a: Anchor, b: Anchor): { d: string; mid: Point } {
  const pull = Math.min(140, Math.hypot(b.x - a.x, b.y - a.y) / 2.5);
  const c1 = { x: a.x + a.nx * pull, y: a.y + a.ny * pull };
  const c2 = { x: b.x + b.nx * pull, y: b.y + b.ny * pull };
  // The point halfway along a cubic Bézier.
  const mid = { x: (a.x + 3 * c1.x + 3 * c2.x + b.x) / 8, y: (a.y + 3 * c1.y + 3 * c2.y + b.y) / 8 };
  return { d: `M${a.x},${a.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${b.x},${b.y}`, mid };
}

function Lines({
  links,
  nodes,
  at,
  heightOf,
  selection,
  near,
  connecting,
}: {
  links: BoardLink[];
  nodes: Map<number, BoardNode>;
  at(id: number): Point | undefined;
  heightOf(node: BoardNode): number;
  selection: BoardSelection;
  near: Set<number> | null;
  connecting: { from: Point; fromNode: BoardNode; to: Point } | null;
}) {
  return (
    <svg className="board-lines" width="1" height="1">
      {links.map((k) => {
        const a = nodes.get(k.from_node_id)!;
        const b = nodes.get(k.to_node_id)!;
        const pa = at(a.id)!;
        const pb = at(b.id)!;
        const [ha, hb] = [heightOf(a), heightOf(b)];
        const { d, mid } = curve(edge(pa, ha, centre(pb, hb)), edge(pb, hb, centre(pa, ha)));
        const selected = selection?.type === "link" && selection.id === k.id;
        const touches = selection?.type === "node" && (k.from_node_id === selection.id || k.to_node_id === selection.id);
        const faded = near && !touches;
        const label = k.rule === "user" ? k.reason : selected || touches ? (RULE_LABELS[k.rule] ?? k.rule) : "";
        const classes = ["board-line", `is-${k.status}`, k.rule === "user" && "is-user", (selected || touches) && "is-hot", faded && "is-faded"];
        return (
          <g key={k.id} className={classes.filter(Boolean).join(" ")}>
            <path d={d} className="line-hit link-hit" data-link-id={k.id}>
              <title>{`${a.label} → ${b.label}: ${k.reason || RULE_LABELS[k.rule] || k.rule}`}</title>
            </path>
            <path d={d} className="line-draw" />
            {label && (
              <foreignObject x={mid.x - 90} y={mid.y - 12} width={180} height={24} className="line-label-box">
                <div className={`line-label${selected ? " is-selected" : ""}`} data-link-id={k.id}>
                  {label}
                </div>
              </foreignObject>
            )}
          </g>
        );
      })}
      {connecting && (
        <path
          className="board-line is-drawing"
          d={(() => {
            const a = edge(connecting.from, heightOf(connecting.fromNode), connecting.to);
            return `M${a.x},${a.y} L${connecting.to.x},${connecting.to.y}`;
          })()}
        />
      )}
    </svg>
  );
}

function QuickNote({
  at,
  pending,
  onCancel,
  onSubmit,
}: {
  at: Point;
  pending: boolean;
  onCancel(): void;
  onSubmit(label: string): void;
}) {
  const [label, setLabel] = useState("");
  return (
    <form
      className="board-quick"
      style={{ transform: `translate(${at.x}px, ${at.y}px)`, width: CARD_WIDTH }}
      onSubmit={(e) => {
        e.preventDefault();
        if (label.trim()) onSubmit(label.trim());
      }}
    >
      <input
        autoFocus
        aria-label="New note"
        placeholder="Type a note, then Enter"
        value={label}
        disabled={pending}
        onChange={(e) => setLabel(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && onCancel()}
        onBlur={() => !label.trim() && onCancel()}
      />
    </form>
  );
}
