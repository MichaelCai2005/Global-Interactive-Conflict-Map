import type { Board, BoardNode } from "./api";

// Where cards go on the board canvas before anyone moves them: a mind map that reads left
// to right. Articles and hand-added cards start the first column; each later column holds
// what the one before links to, kept next to the card it hangs off. Cards someone moved
// keep their saved spot.

export const CARD_WIDTH = 220;
const COLUMN_GAP = 90;
const ROW_GAP = 18;
const IMAGE_HEIGHT = 120;

export interface Point {
  x: number;
  y: number;
}

/** Roughly how tall a card renders, so stacked cards don't overlap. */
export function cardHeight(node: Pick<BoardNode, "label" | "image_url" | "time_start" | "source_url" | "status">): number {
  const lines = Math.min(3, Math.ceil(node.label.length / 30));
  let h = 28 + lines * 19 + 22;
  if (node.image_url) h += IMAGE_HEIGHT;
  if (node.status === "suggested") h += 30;
  return h;
}

const KIND_ORDER = ["article", "link", "note", "claim", "place", "actor", "event", "flight", "fire", "vessel"];

function order(a: BoardNode, b: BoardNode): number {
  const k = KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind);
  if (k !== 0) return k;
  return (b.time_start ?? "").localeCompare(a.time_start ?? "") || a.id - b.id;
}

/** Positions for every shown card: saved ones as saved, the rest laid out. `heightOf`
 * gives a card's rendered height once the canvas has measured it. */
export function layoutBoard(
  board: Pick<Board, "nodes" | "links">,
  shown: (n: BoardNode) => boolean,
  heightOf: (n: BoardNode) => number = cardHeight,
): Map<number, Point> {
  const nodes = board.nodes.filter(shown);
  const ids = new Set(nodes.map((n) => n.id));
  const neighbours = new Map<number, number[]>();
  for (const k of board.links) {
    if (!ids.has(k.from_node_id) || !ids.has(k.to_node_id) || k.status === "rejected") continue;
    neighbours.set(k.from_node_id, [...(neighbours.get(k.from_node_id) ?? []), k.to_node_id]);
    neighbours.set(k.to_node_id, [...(neighbours.get(k.to_node_id) ?? []), k.from_node_id]);
  }
  const byId = new Map(nodes.map((n) => [n.id, n]));

  // Columns by distance from the roots, breadth first; each card remembers its parent.
  const roots = nodes.filter((n) => n.kind === "article" || n.created_by === "user").sort(order);
  const depth = new Map<number, number>();
  const parent = new Map<number, number>();
  const queue: number[] = [];
  for (const r of roots) {
    depth.set(r.id, 0);
    queue.push(r.id);
  }
  // A board with no article or user card yet starts from its first card.
  if (queue.length === 0 && nodes.length > 0) {
    const first = [...nodes].sort(order)[0]!;
    depth.set(first.id, 0);
    queue.push(first.id);
  }
  while (queue.length) {
    const id = queue.shift()!;
    const next = (neighbours.get(id) ?? []).map((n) => byId.get(n)!).sort(order);
    for (const n of next) {
      if (depth.has(n.id)) continue;
      depth.set(n.id, depth.get(id)! + 1);
      parent.set(n.id, id);
      queue.push(n.id);
    }
  }
  // Cards linked to nothing go in a column of their own at the end.
  const deepest = Math.max(0, ...depth.values());
  for (const n of nodes) if (!depth.has(n.id)) depth.set(n.id, deepest + 1);

  const columns: BoardNode[][] = [];
  for (const n of nodes) (columns[depth.get(n.id)!] ??= []).push(n);

  const at = new Map<number, Point>();
  for (const n of nodes) if (n.board_x !== null && n.board_y !== null) at.set(n.id, { x: n.board_x, y: n.board_y });

  // A card with many children (a place with 25 events) gets them as a block of a few
  // columns rather than one very tall one, so the board stays wide rather than tall.
  let x = 0;
  for (const column of columns) {
    if (!column) continue;
    const parentY = (n: BoardNode) => {
      const p = parent.get(n.id);
      return p === undefined ? 0 : (at.get(p)?.y ?? 0);
    };
    const groups = new Map<number, BoardNode[]>();
    for (const n of column) {
      if (at.has(n.id)) continue;
      const p = parent.get(n.id) ?? -1;
      groups.set(p, [...(groups.get(p) ?? []), n]);
    }
    // Siblings stay together, in the order their parents sit.
    const ordered = [...groups.values()]
      .map((g) => g.sort(order))
      .sort((a, b) => parentY(a[0]!) - parentY(b[0]!));
    let free = -Infinity;
    let widest = 1;
    for (const group of ordered) {
      const tall = Math.min(group.length, Math.max(4, Math.ceil(Math.sqrt(group.length * 2))));
      const cols = Math.ceil(group.length / tall);
      const rows = Math.ceil(group.length / cols);
      widest = Math.max(widest, cols);
      // As close to the parent's height as the cards above allow.
      let y = Math.max(free, parentY(group[0]!));
      for (let r = 0; r < rows; r++) {
        const row = group.slice(r * cols, r * cols + cols);
        row.forEach((n, c) => at.set(n.id, { x: x + c * (CARD_WIDTH + ROW_GAP), y }));
        y += Math.max(...row.map(heightOf)) + ROW_GAP;
      }
      free = y;
    }
    x += widest * (CARD_WIDTH + ROW_GAP) - ROW_GAP + COLUMN_GAP;
  }
  return at;
}

/** A spot for a new card near `near` that no shown card covers. */
export function freeSpot(near: Point, taken: Iterable<Point>): Point {
  const boxes = [...taken];
  const clear = (p: Point) =>
    boxes.every((b) => Math.abs(b.x - p.x) > CARD_WIDTH + 10 || Math.abs(b.y - p.y) > 110);
  for (let ring = 0; ring < 12; ring++) {
    for (let i = 0; i < Math.max(1, ring * 6); i++) {
      const angle = (i / Math.max(1, ring * 6)) * Math.PI * 2;
      const p = { x: near.x + Math.cos(angle) * ring * 130, y: near.y + Math.sin(angle) * ring * 90 };
      if (clear(p)) return { x: Math.round(p.x), y: Math.round(p.y) };
    }
  }
  return near;
}
