import { useCallback, useState } from "react";
import { readStored, writeStored } from "./storage";

/**
 * Things to try: the app's features in the order a newcomer is best met with them, offered
 * one at a time so the whole app doesn't arrive at once. Each is ticked off the first time
 * it is used, however the user found it.
 */
export type Discovery = "event" | "time" | "filters" | "risk" | "story" | "board" | "account";

export interface DiscoveryItem {
  key: Discovery;
  title: string;
  hint: string;
  /** The data-tour value of the control "Show me" points at. */
  target: string;
}

export const DISCOVERIES: DiscoveryItem[] = [
  {
    key: "event",
    title: "Open an event",
    hint: "Click any dot on the map to read what happened there, with the news reports about it.",
    target: "map",
  },
  {
    key: "time",
    title: "Move through time",
    hint: "Drag the highlighted window on the timeline, or press play to watch events unfold step by step.",
    target: "timeline",
  },
  {
    key: "filters",
    title: "Narrow it down",
    hint: "Show only violence or only signals, or pick a country. More filters chooses data sources and event types.",
    target: "filters",
  },
  {
    key: "risk",
    title: "See where risk is rising",
    hint: "The Risk tab scores every country each week and flags sudden surges. Click a country to see why.",
    target: "tab-risk",
  },
  {
    key: "story",
    title: "Replay a past conflict",
    hint: "Stories & help has guided replays of wars such as Syria's and the invasion of Ukraine.",
    target: "help",
  },
  {
    key: "board",
    title: "Collect findings on a board",
    hint: "Boards are pin-boards for research: gather events, links and notes, connect them, and see them on the map.",
    target: "tab-board",
  },
  {
    key: "account",
    title: "Keep a watchlist",
    hint: "A free account keeps a watchlist of places, a list of follow-up tasks, and saved views.",
    target: "account",
  },
];

const DONE_KEY = "conflict-map:discovered";

export function useDiscoveries() {
  const [done, setDone] = useState<ReadonlySet<Discovery>>(() => new Set(parse(readStored(DONE_KEY))));
  const mark = useCallback((key: Discovery) => {
    setDone((prev) => {
      if (prev.has(key)) return prev;
      const next = new Set(prev).add(key);
      writeStored(DONE_KEY, JSON.stringify([...next]));
      return next;
    });
  }, []);
  return { done, mark };
}

function parse(stored: string | null): Discovery[] {
  try {
    const value: unknown = JSON.parse(stored ?? "[]");
    return Array.isArray(value) ? value.filter((k): k is Discovery => DISCOVERIES.some((d) => d.key === k)) : [];
  } catch {
    return [];
  }
}
