import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Board } from "./api";
import { BoardPanel, storyWindow } from "./BoardPanel";

const BOARD: Board = {
  id: 5,
  title: "Malian forces battle JNIM near Testville",
  origin: "article",
  prompt: "",
  source_url: "https://news.example/a",
  anchor_date: "2026-10-16",
  extractor: "gazetteer",
  notes: "",
  created_at: "2026-10-20T00:00:00Z",
  updated_at: "2026-10-20T00:00:00Z",
  nodes: [
    node(1, "article", "Malian forces battle JNIM near Testville", "accepted"),
    node(2, "place", "Testville", "suggested"),
    node(3, "event", "Battle in Testville", "suggested", { violent: true }),
  ],
  links: [
    {
      id: 10,
      from_node_id: 1,
      to_node_id: 2,
      rule: "mentions",
      reason: "The article names Testville",
      evidence: { quote: "Malian troops clashed near Testville." },
      confidence: 0.9,
      status: "suggested",
      created_by: "rule",
    },
    {
      id: 11,
      from_node_id: 2,
      to_node_id: 3,
      rule: "near",
      reason: "Battle in Testville, at the same spot, 5 days before the article's date",
      evidence: {},
      confidence: 0.84,
      status: "suggested",
      created_by: "rule",
    },
  ],
};

function node(id: number, kind: Board["nodes"][number]["kind"], label: string, status: Board["nodes"][number]["status"], attributes = {}) {
  return {
    id,
    key: `${kind}:${id}`,
    kind,
    label,
    detail: "",
    event_id: kind === "event" ? 99 : null,
    latitude: 14.5,
    longitude: -4.2,
    geo_basis: "exact",
    time_start: kind === "place" ? null : "2026-10-11T00:00:00Z",
    time_end: null,
    source_name: null,
    source_url: null,
    quote: null,
    status,
    created_by: "rule" as const,
    attributes,
  };
}

function mockApi() {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      let body: unknown = BOARD;
      if (url === "/api/boards") body = [{ ...BOARD, nodes: 3, links: 2, accepted: 1 }];
      if (url.endsWith("/review")) {
        const { link_ids } = JSON.parse(String(init?.body)) as { link_ids: number[] };
        body = { ...BOARD, links: BOARD.links.map((k) => (link_ids.includes(k.id) ? { ...k, status: "accepted" } : k)) };
      }
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return calls;
}

function renderPanel(boardId: number | null, overrides = {}) {
  const props = {
    boardId,
    selectedNodeId: null,
    mapCenter: { lon: 0, lat: 0 },
    onOpen: vi.fn(),
    onSelectNode: vi.fn(),
    onFocus: vi.fn(),
    onWindow: vi.fn(),
    ...overrides,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <BoardPanel {...props} />
    </QueryClientProvider>,
  );
  return props;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("BoardPanel", () => {
  it("lists boards and opens one at its story's time", async () => {
    mockApi();
    const props = renderPanel(null);
    await userEvent.click(await screen.findByRole("button", { name: BOARD.title }));
    expect(props.onOpen).toHaveBeenCalledWith(5);
    expect(props.onWindow).toHaveBeenCalledWith({ start: "2026-08-17", end: "2026-10-19" });
  });

  it("shows each suggested link with its reason and quote, strongest first", async () => {
    mockApi();
    renderPanel(5);
    expect(await screen.findByText("The article names Testville")).toBeTruthy();
    expect(screen.getByText("“Malian troops clashed near Testville.”")).toBeTruthy();
    const reasons = screen.getAllByText(/Testville/, { selector: ".board-link p" }).map((p) => p.textContent);
    expect(reasons[0]).toBe("The article names Testville");
    expect(screen.getByText("To review (2)")).toBeTruthy();
  });

  it("accepts links one at a time or all strong ones together", async () => {
    const calls = mockApi();
    renderPanel(5);
    await userEvent.click(await screen.findByRole("button", { name: "Accept the 2 links at 80% or more" }));
    const review = calls.find((c) => c.url.endsWith("/boards/5/review"))!;
    expect(JSON.parse(String(review.init?.body))).toEqual({ status: "accepted", link_ids: [10, 11] });
  });

  it("links the globe to the board, accepted items by default", async () => {
    mockApi();
    renderPanel(5);
    const open = await screen.findByRole("link", { name: "Open in 3D globe" });
    expect(open.getAttribute("href")).toBe("http://localhost:4173/?welcome=0&board=5");
    await userEvent.click(screen.getByRole("button", { name: "Everything not rejected" }));
    expect(open.getAttribute("href")).toBe("http://localhost:4173/?welcome=0&board=5&include=all");
    expect(screen.getByRole("link", { name: "Download for globe" }).getAttribute("href")).toBe(
      "/api/boards/5/bundle?include=all",
    );
  });

  it("flies to a node when its name is clicked", async () => {
    mockApi();
    const props = renderPanel(5);
    // The node list's button, not the link card's end with the same name.
    const buttons = await screen.findAllByRole("button", { name: /^Battle in Testville/ });
    await userEvent.click(buttons.find((b) => b.classList.contains("node-label"))!);
    expect(props.onFocus).toHaveBeenCalledWith(-4.2, 14.5);
    expect(props.onSelectNode).toHaveBeenCalledWith(3);
  });

  it("knows the window a story covers", () => {
    expect(storyWindow({ anchor_date: "2026-10-16" })).toEqual({ start: "2026-08-17", end: "2026-10-19" });
    expect(storyWindow({ anchor_date: null })).toBeNull();
  });
});
