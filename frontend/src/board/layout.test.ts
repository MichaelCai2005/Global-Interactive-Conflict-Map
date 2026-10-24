import { describe, expect, it } from "vitest";
import type { BoardLink, BoardNode } from "./api";
import { CARD_WIDTH, cardHeight, freeSpot, layoutBoard } from "./layout";

function node(id: number, kind: BoardNode["kind"], extra: Partial<BoardNode> = {}): BoardNode {
  return {
    id,
    key: `${kind}:${id}`,
    kind,
    label: `${kind} ${id}`,
    detail: "",
    event_id: null,
    latitude: null,
    longitude: null,
    geo_basis: null,
    time_start: null,
    time_end: null,
    source_name: null,
    source_url: null,
    quote: null,
    status: "accepted",
    created_by: "rule",
    attributes: {},
    board_x: null,
    board_y: null,
    image_url: null,
    ...extra,
  };
}

function link(id: number, from: number, to: number, status: BoardLink["status"] = "accepted"): BoardLink {
  return { id, from_node_id: from, to_node_id: to, rule: "near", reason: "", evidence: {}, confidence: 0.5, status, created_by: "rule" };
}

const all = () => true;

describe("layoutBoard", () => {
  it("reads left to right from the article, children beside their parent", () => {
    const nodes = [node(1, "article"), node(2, "place"), node(3, "place"), node(4, "event"), node(5, "event")];
    const links = [link(1, 1, 2), link(2, 1, 3), link(3, 3, 4), link(4, 3, 5)];
    const at = layoutBoard({ nodes, links }, all);
    expect(at.get(1)!.x).toBe(0);
    expect(at.get(2)!.x).toBe(at.get(3)!.x);
    expect(at.get(4)!.x).toBeGreaterThan(at.get(3)!.x + CARD_WIDTH);
    // Place 3's events start level with it, below nothing else.
    expect(at.get(4)!.y).toBe(at.get(3)!.y);
    expect(at.get(5)!.y).toBeGreaterThan(at.get(4)!.y);
  });

  it("never stacks cards of one column on top of each other", () => {
    const nodes = [node(1, "article"), ...[2, 3, 4, 5].map((i) => node(i, "event", { image_url: i % 2 ? "x" : null }))];
    const links = [2, 3, 4, 5].map((i) => link(i, 1, i));
    const at = layoutBoard({ nodes, links }, all);
    const column = [2, 3, 4, 5].map((i) => ({ y: at.get(i)!.y, h: cardHeight(nodes[i - 1]!) })).sort((a, b) => a.y - b.y);
    for (let i = 1; i < column.length; i++) expect(column[i]!.y).toBeGreaterThanOrEqual(column[i - 1]!.y + column[i - 1]!.h);
  });

  it("keeps groups apart when a block's last row is short", () => {
    // Two places with five events each: each block is two columns wide, three rows tall.
    const nodes = [node(1, "article"), node(2, "place"), node(3, "place"), ...[4, 5, 6, 7, 8, 9, 10, 11, 12, 13].map((i) => node(i, "event"))];
    const links = [link(1, 1, 2), link(2, 1, 3), ...[4, 5, 6, 7, 8].map((i) => link(i, 2, i)), ...[9, 10, 11, 12, 13].map((i) => link(i, 3, i))];
    const at = layoutBoard({ nodes, links }, all);
    const cards = nodes.slice(3).map((n) => ({ ...at.get(n.id)!, h: cardHeight(n) }));
    for (const a of cards)
      for (const b of cards)
        if (a !== b && Math.abs(a.x - b.x) < CARD_WIDTH) expect(a.y >= b.y + b.h || b.y >= a.y + a.h).toBe(true);
  });

  it("keeps saved spots, skips hidden cards and puts loose cards last", () => {
    const nodes = [
      node(1, "article"),
      node(2, "place", { board_x: 900, board_y: -50 }),
      node(3, "note", { created_by: "user" }),
      node(4, "event", { status: "rejected" }),
      node(5, "event"),
      node(6, "place"),
    ];
    const at = layoutBoard({ nodes, links: [link(1, 1, 2), link(2, 1, 6)] }, (n) => n.status !== "rejected");
    expect(at.get(2)).toEqual({ x: 900, y: -50 });
    expect(at.has(4)).toBe(false);
    // A note the user added is a root, like an article; an unlinked event comes last.
    expect(at.get(3)!.x).toBe(0);
    expect(at.get(5)!.x).toBeGreaterThan(at.get(6)!.x);
  });

  it("lays out a board with no article from its first card", () => {
    const nodes = [node(7, "place"), node(8, "event")];
    const at = layoutBoard({ nodes, links: [link(1, 7, 8)] }, all);
    expect(at.get(7)!.x).toBeLessThan(at.get(8)!.x);
  });
});

describe("freeSpot", () => {
  it("finds a spot no card covers", () => {
    const taken = [{ x: 0, y: 0 }];
    const spot = freeSpot({ x: 0, y: 0 }, taken);
    expect(Math.abs(spot.x) > CARD_WIDTH || Math.abs(spot.y) > 110).toBe(true);
    expect(freeSpot({ x: 5000, y: 0 }, taken)).toEqual({ x: 5000, y: 0 });
  });
});
