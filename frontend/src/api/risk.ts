// Weekly risk scores (backend/app/risk.py, served by backend/app/api/risk.py). Weeks start
// on Monday; any date can be passed and the backend uses the week it falls in.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { queryString, request } from "./client";
import type { EventOut } from "./types";

export type RiskComponent = "history" | "surge" | "spread" | "signal";
export type RiskTrend = "new" | "intensifying" | "diminishing" | "persistent";

/** Points each component adds to the score; they sum to the score (0-100). */
export type RiskPoints = Record<RiskComponent, number>;

export interface RiskRegion {
  iso3: string;
  name: string;
  latitude: number | null;
  longitude: number | null;
  score: number;
  /** Change since the previous week; null in the first scored week. */
  change: number | null;
  points: RiskPoints;
  trend: RiskTrend | null;
  surge_alarm: boolean;
  provisional: boolean;
}

export interface RiskWeek {
  week: string;
  previous_week: string | null;
  first_week: string;
  last_week: string;
  /** UCDP and ACLED do not cover this week yet. */
  provisional: boolean;
  regions: RiskRegion[];
}

export interface RiskPoint {
  week: string;
  score: number;
  change: number | null;
  points: RiskPoints;
  trend: RiskTrend | null;
  surge_alarm: boolean;
  provisional: boolean;
  violent_events: number;
  deaths: number;
  gdelt_events: number;
}

export interface RiskSeries {
  iso3: string;
  name: string;
  neighbours: string[];
  points: RiskPoint[];
}

export interface RiskComponentChange {
  component: RiskComponent;
  points: number;
  previous_points: number | null;
  change: number | null;
  explanation: string;
}

export interface RiskExplanation {
  iso3: string;
  name: string;
  week: string;
  previous_week: string | null;
  score: number;
  previous_score: number | null;
  change: number | null;
  trend: RiskTrend | null;
  surge_alarm: boolean;
  provisional: boolean;
  summary: string;
  /** Biggest change first. */
  components: RiskComponentChange[];
  /** The week's deadliest and most reported events. */
  events: EventOut[];
  neighbours: { iso3: string; name: string; score: number; history: number }[];
}

export type RiskSort = "score" | "rise" | "fall";

export function useRiskWeek(week: string | null, sort: RiskSort = "score", limit = 300, enabled = true) {
  const params = { week, sort, limit };
  return useQuery({
    queryKey: ["risk", params],
    queryFn: () => request<RiskWeek>(`/risk${queryString(params)}`),
    staleTime: 10 * 60_000,
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useRiskSeries(iso3: string | null, start: string, end: string) {
  const params = { start, end };
  return useQuery({
    queryKey: ["risk-series", iso3, params],
    queryFn: () => request<RiskSeries>(`/risk/${iso3}${queryString(params)}`),
    staleTime: 10 * 60_000,
    placeholderData: keepPreviousData,
    enabled: iso3 !== null,
  });
}

export function useRiskExplanation(iso3: string | null, week: string | null) {
  return useQuery({
    queryKey: ["risk-explain", iso3, week],
    queryFn: () => request<RiskExplanation>(`/risk/${iso3}/weeks/${week}`),
    staleTime: 10 * 60_000,
    enabled: iso3 !== null && week !== null,
  });
}

/** Stacking order, bottom to top. Colors are adjacent slots validated on the dark surface. */
export const RISK_COMPONENTS: { key: RiskComponent; label: string; color: string; question: string }[] = [
  { key: "history", label: "History", color: "#d95926", question: "How violent lately?" },
  { key: "spread", label: "Spread", color: "#199e70", question: "Are neighbours heating up?" },
  { key: "surge", label: "Surge", color: "#c98500", question: "Is this week abnormal here?" },
  { key: "signal", label: "Signal", color: "#3987e5", question: "Is the news turning?" },
];

/** The Monday of the week a date falls in, as the backend counts weeks. */
export function weekOf(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7));
  return date.toISOString().slice(0, 10);
}

/** Map points for the risk layer: one circle per country, sized and colored by score. */
export function riskGeoJson(week: RiskWeek | undefined): GeoJSON.FeatureCollection<GeoJSON.Point> {
  return {
    type: "FeatureCollection",
    features: (week?.regions ?? [])
      .filter((r) => r.latitude !== null && r.longitude !== null && r.score >= 1)
      .map((r) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [r.longitude!, r.latitude!] },
        properties: {
          iso3: r.iso3,
          name: r.name,
          score: Math.round(r.score),
          change: r.change === null ? null : Math.round(r.change),
          trend: r.trend,
          alarm: r.surge_alarm,
        },
      })),
  };
}
