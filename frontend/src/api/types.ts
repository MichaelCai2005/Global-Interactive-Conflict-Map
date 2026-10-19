// Mirrors backend/app/schemas.py. Dates are ISO strings (YYYY-MM-DD).

import type { FeatureCollection, Point } from "geojson";

export type Bbox = [minLon: number, minLat: number, maxLon: number, maxLat: number];
export type Interval = "day" | "week" | "month";

export interface EventOut {
  id: number;
  source: string;
  source_event_id: string;
  event_date: string;
  end_date: string | null;
  event_type: string;
  is_violent: boolean;
  country: string | null;
  admin1: string | null;
  location_name: string | null;
  latitude: number;
  longitude: number;
  geo_precision: "exact" | "admin" | "country";
  actor1: string | null;
  actor2: string | null;
  fatalities_best: number | null;
  fatalities_low: number | null;
  fatalities_high: number | null;
  report_count: number;
  tone: number | null;
  source_url: string | null;
  conflict_id: string | null;
  duplicate_of_id: number | null;
  attributes: Record<string, unknown>;
}

export interface EventPage {
  total: number;
  limit: number;
  offset: number;
  items: EventOut[];
}

export interface LinkedEvent {
  link_type: string;
  distance_km: number;
  day_gap: number;
  score: number;
  event: EventOut;
}

export interface EventDetail extends EventOut {
  duplicates: LinkedEvent[];
  duplicate_of: LinkedEvent | null;
}

export interface TimelineBucket {
  period: string;
  violent_events: number;
  signal_events: number;
  fatalities: number;
}

export interface Timeline {
  interval: Interval;
  buckets: TimelineBucket[];
}

export interface Summary {
  violent_events: number;
  signal_events: number;
  fatalities: number;
}

export interface Facet {
  value: string;
  count: number;
}

export interface Facets {
  sources: Facet[];
  event_types: (Facet & { is_violent: boolean })[];
  countries: Facet[];
  first_date: string | null;
  last_date: string | null;
}

export interface CountrySummary extends Summary {
  country: string;
  bbox: Bbox;
}

export interface PointProps {
  id: number;
  date: string;
  day: number;
  type: string;
  violent: boolean;
  deaths: number;
  source: string;
  precision: EventOut["geo_precision"];
}

export interface CellProps {
  events: number;
  violent: number;
  signals: number;
  deaths: number;
}

export type MapLayer =
  | {
      mode: "points";
      total: number;
      cell_size: null;
      features: FeatureCollection<Point, PointProps>;
    }
  | {
      mode: "grid";
      total: number;
      cell_size: number;
      features: FeatureCollection<Point, CellProps>;
    };

export interface WatchItem {
  id: number;
  name: string;
  country: string | null;
  bbox: string | null;
  notes: string;
  created_at: string;
}

export type TaskStatus = "open" | "in_progress" | "done";
export type TaskPriority = "low" | "normal" | "high";

export interface Task {
  id: number;
  title: string;
  notes: string;
  status: TaskStatus;
  priority: TaskPriority;
  event_id: number | null;
  watch_item_id: number | null;
  event: Pick<
    EventOut,
    "id" | "event_date" | "event_type" | "country" | "location_name" | "latitude" | "longitude"
  > | null;
  created_at: string;
  updated_at: string;
}

export interface TaskInput {
  title: string;
  notes?: string;
  status?: TaskStatus;
  priority?: TaskPriority;
  event_id?: number | null;
  watch_item_id?: number | null;
}
