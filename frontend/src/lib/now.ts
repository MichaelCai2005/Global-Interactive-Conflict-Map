import type { EventOut, Facets } from "../api/types";
import { type DateWindow, addDays, daysBetween } from "./dates";

// "Now" mostly means the newest data, not today's date: UCDP's monthly files arrive a few
// weeks late, and a day-long window ending on the newest date holds only part of a day. The
// one exception is the news in the last hours, which GDELT posts every 15 minutes and which
// the map filters by when GDELT first published each event (see reportedSince).

/** The `days` days ending on the newest date in the data. */
export function latestWindow(last: string, days: number): DateWindow {
  return { start: addDays(last, -(days - 1)), end: last };
}

/** Sources that count deaths. GDELT counts news reports, not deaths. */
const DEATH_SOURCES = ["ucdp", "acled"];

/**
 * The newest date with death counts, among the sources the filters allow. Recent deaths
 * come only from UCDP's monthly files, so they stop weeks before the news events do.
 */
export function deathsThrough(sources: Facets["sources"], allowed: string[]): string | null {
  const dates = sources
    .filter((s) => DEATH_SOURCES.includes(s.value) && (allowed.length === 0 || allowed.includes(s.value)))
    .map((s) => s.last_date)
    .filter((d): d is string => d !== null);
  return dates.length ? dates.reduce((a, b) => (a > b ? a : b)) : null;
}

/** How long ago a date was, in words: "today", "yesterday", "5 days ago", "3 weeks ago". */
export function describeAge(date: string, today: string): string {
  const days = daysBetween(date, today);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 14) return `${days} days ago`;
  if (days < 60) return `${Math.round(days / 7)} weeks ago`;
  if (days < 730) return `${Math.round(days / 30.4)} months ago`;
  return `${Math.round(days / 365)} years ago`;
}

/** The Sunday on or before a date: the end of the newest whole week (weeks start on Monday). */
export function lastWholeWeek(date: string): string {
  return addDays(date, -new Date(`${date}T00:00:00Z`).getUTCDay());
}

/**
 * A readable title from a news link's address, which usually ends in the headline:
 * ".../2026/10/18/fatalities-reported-after-incident-at-base/" gives "Fatalities reported
 * after incident at base". Null when the address has no words to use.
 */
export function headlineFromUrl(url: string): string | null {
  let path: string;
  try {
    path = new URL(url).pathname;
  } catch {
    return null;
  }
  const slug = path
    .split("/")
    // Some sites put the article id before the slug: "26667668.musk-speaks-starlink".
    .map((part) => part.replace(/\.(html?|php|aspx?)$/i, "").replace(/^\d+\./, ""))
    .filter((part) => /[a-z]{3,}-[a-z]{2,}/i.test(part))
    .sort((a, b) => b.length - a.length)[0];
  if (!slug) return null;
  const words = slug
    .split(/[-_]+/)
    .filter((w) => !/^\d+$/.test(w) && !/^[a-z]*\d{5,}$/i.test(w))
    .join(" ");
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : null;
}

type StoryEvent = Pick<
  EventOut,
  "event_date" | "country" | "latitude" | "longitude" | "geo_precision" | "source_url"
>;

/** How far apart two places can be and still be one story, by the vaguer of the two. */
const SAME_STORY_KM = { exact: 100, admin: 500, country: Infinity };

/**
 * The first event of each story, so one incident told many times takes one line. GDELT codes
 * a story once per pair of actors and per place it names: one fire at a base came out as six
 * events placed at the town, the province and the whole country. Two events are one story
 * when they share an article or headline, or fall on the same day in the same country close
 * enough together, given how precisely each is placed.
 */
export function oneEachStory<T extends StoryEvent>(events: T[]): T[] {
  const kept: T[] = [];
  for (const e of events) {
    if (!kept.some((k) => sameStory(k, e))) kept.push(e);
  }
  return kept;
}

function sameStory(a: StoryEvent, b: StoryEvent): boolean {
  if (a.source_url && a.source_url === b.source_url) return true;
  const headline = a.source_url ? headlineFromUrl(a.source_url) : null;
  if (headline && b.source_url && headline === headlineFromUrl(b.source_url)) return true;
  if (a.event_date !== b.event_date || !a.country || a.country !== b.country) return false;
  const limit = Math.max(SAME_STORY_KM[a.geo_precision], SAME_STORY_KM[b.geo_precision]);
  return distanceKm(a, b) <= limit;
}

/** Great-circle distance in km. */
function distanceKm(a: StoryEvent, b: StoryEvent): number {
  const rad = Math.PI / 180;
  const dLat = (b.latitude - a.latitude) * rad;
  const dLon = (b.longitude - a.longitude) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.latitude * rad) * Math.cos(b.latitude * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

const QUARTER_HOUR = 15 * 60_000;

/**
 * The ISO time `hours` before `now`, rounded down to GDELT's quarter hour so the queries
 * built on it stay the same, and stay cached, until the next file could have arrived.
 */
export function reportedSince(hours: number, now: number = Date.now()): string {
  return new Date(Math.floor(now / QUARTER_HOUR) * QUARTER_HOUR - hours * 3_600_000).toISOString();
}

/** How long ago a time was, in words: "just now", "40 min ago", "5 h ago", "2 days ago". */
export function describeTimeAgo(iso: string, now: number = Date.now()): string {
  const minutes = Math.round((now - Date.parse(iso)) / 60_000);
  if (minutes < 15) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} days ago`;
}
