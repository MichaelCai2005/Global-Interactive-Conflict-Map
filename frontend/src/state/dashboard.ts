import type { Bbox } from "../api/types";
import { type DateWindow, addDays } from "../lib/dates";

export type Violence = "all" | "violent" | "signals";
export type Panel = "overview" | "risk" | "watchlist" | "tasks";

export interface Filters {
  sources: string[];
  violence: Violence;
  types: string[];
  country: string | null;
}

export interface Camera {
  lon: number;
  lat: number;
  zoom: number;
}

export interface DashboardState {
  filters: Filters;
  /** The stretch of time shown on the map. Null until the data's date range is known. */
  window: DateWindow | null;
  /** The stretch of time the timeline spans. Null means all the data. */
  range: DateWindow | null;
  camera: Camera;
  /** What the map currently shows; null when it shows the whole world. */
  viewBbox: Bbox | null;
  /** Whether the timeline and overview count only events in the map view. */
  followView: boolean;
  selectedEventId: number | null;
  panel: Panel;
  playing: boolean;
  speed: number;
}

export const EMPTY_FILTERS: Filters = { sources: [], violence: "all", types: [], country: null };

export const DEFAULT_CAMERA: Camera = { lon: 20, lat: 20, zoom: 1.6 };

export function initialState(search: string): DashboardState {
  const q = new URLSearchParams(search);
  const list = (key: string) => q.get(key)?.split(",").filter(Boolean) ?? [];
  const date = (key: string) => {
    const value = q.get(key);
    return value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null;
  };
  const pair = (a: string, b: string): DateWindow | null => {
    const start = date(a);
    const end = date(b);
    return start && end && start <= end ? { start, end } : null;
  };
  const violence = q.get("class");
  const [lon, lat, zoom] = (q.get("at") ?? "").split(",").map(Number);
  const panel = q.get("panel");
  const event = Number(q.get("event"));
  return {
    filters: {
      sources: list("source"),
      violence: violence === "violent" || violence === "signals" ? violence : "all",
      types: list("type"),
      country: q.get("country") || null,
    },
    window: pair("from", "to"),
    range: pair("range_from", "range_to"),
    camera:
      Number.isFinite(lon) && Number.isFinite(lat) && Number.isFinite(zoom)
        ? { lon: lon!, lat: lat!, zoom: zoom! }
        : DEFAULT_CAMERA,
    viewBbox: null,
    followView: q.get("follow") !== "0",
    selectedEventId: Number.isInteger(event) && event > 0 ? event : null,
    panel: panel === "risk" || panel === "watchlist" || panel === "tasks" ? panel : "overview",
    playing: false,
    speed: 1,
  };
}

/** The parts of the state worth keeping in a shareable link. */
export function toSearch(state: DashboardState): string {
  const q = new URLSearchParams();
  const { filters, window, range, camera } = state;
  if (filters.sources.length) q.set("source", filters.sources.join(","));
  if (filters.violence !== "all") q.set("class", filters.violence);
  if (filters.types.length) q.set("type", filters.types.join(","));
  if (filters.country) q.set("country", filters.country);
  if (window) {
    q.set("from", window.start);
    q.set("to", window.end);
  }
  if (range) {
    q.set("range_from", range.start);
    q.set("range_to", range.end);
  }
  q.set("at", [camera.lon.toFixed(3), camera.lat.toFixed(3), camera.zoom.toFixed(2)].join(","));
  if (!state.followView) q.set("follow", "0");
  if (state.selectedEventId) q.set("event", String(state.selectedEventId));
  if (state.panel !== "overview") q.set("panel", state.panel);
  return q.toString();
}

export type Action =
  | { type: "filters"; filters: Partial<Filters> }
  | { type: "clearFilters" }
  | { type: "window"; window: DateWindow }
  | { type: "range"; range: DateWindow | null }
  | { type: "camera"; camera: Camera; viewBbox: Bbox | null }
  | { type: "followView"; followView: boolean }
  | { type: "select"; eventId: number | null }
  | { type: "panel"; panel: Panel }
  | { type: "play"; playing: boolean }
  | { type: "speed"; speed: number }
  | { type: "story"; range: DateWindow; windowDays: number };

export function reducer(state: DashboardState, action: Action): DashboardState {
  switch (action.type) {
    case "filters":
      return { ...state, filters: { ...state.filters, ...action.filters } };
    case "clearFilters":
      return { ...state, filters: EMPTY_FILTERS };
    case "window":
      return { ...state, window: action.window };
    case "range":
      return { ...state, range: action.range };
    case "camera":
      return { ...state, camera: action.camera, viewBbox: action.viewBbox };
    case "followView":
      return { ...state, followView: action.followView };
    case "select":
      return { ...state, selectedEventId: action.eventId };
    case "panel":
      return { ...state, panel: action.panel };
    case "play":
      return { ...state, playing: action.playing };
    case "speed":
      return { ...state, speed: action.speed };
    case "story":
      return {
        ...state,
        filters: EMPTY_FILTERS,
        range: action.range,
        window: {
          start: action.range.start,
          end: addDays(action.range.start, action.windowDays - 1),
        },
        selectedEventId: null,
        followView: true,
        playing: true,
      };
  }
}
