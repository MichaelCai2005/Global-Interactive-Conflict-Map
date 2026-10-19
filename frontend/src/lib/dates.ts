import type { Interval } from "../api/types";

// Dates are handled as whole UTC days. `day` numbers count days since 1970-01-01, the same
// unit the /map endpoint puts on each point, so the map can fade points by age.

const MS_PER_DAY = 86_400_000;

export function toDay(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Math.round(Date.UTC(y!, m! - 1, d!) / MS_PER_DAY);
}

export function fromDay(day: number): string {
  return new Date(day * MS_PER_DAY).toISOString().slice(0, 10);
}

export function addDays(iso: string, days: number): string {
  return fromDay(toDay(iso) + days);
}

export function daysBetween(start: string, end: string): number {
  return toDay(end) - toDay(start);
}

/** The start of the bucket after `period`, for drawing a bucket's width. */
export function nextPeriod(period: string, interval: Interval): string {
  if (interval === "day") return addDays(period, 1);
  if (interval === "week") return addDays(period, 7);
  const date = new Date(`${period}T00:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() + 1);
  return date.toISOString().slice(0, 10);
}

/** Bucket size that keeps a timeline readable: roughly 50 to 450 bars. */
export function intervalFor(start: string, end: string): Interval {
  const span = daysBetween(start, end);
  if (span > 365 * 6) return "month";
  if (span > 300) return "week";
  return "day";
}

export interface DateWindow {
  start: string;
  end: string;
}

/** How far one playback step moves a window: about a quarter of its length. */
export function stepFor(window: DateWindow): number {
  const length = daysBetween(window.start, window.end) + 1;
  if (length <= 21) return Math.max(1, Math.round(length / 4));
  if (length <= 120) return 7;
  if (length <= 400) return 30;
  return 91;
}

/** Moves a window by `days`, keeping its length and staying inside the domain. */
export function shiftWindow(window: DateWindow, days: number, domain: DateWindow): DateWindow {
  const length = daysBetween(window.start, window.end);
  const min = toDay(domain.start);
  const max = toDay(domain.end) - length;
  const start = Math.min(Math.max(toDay(window.start) + days, min), Math.max(min, max));
  return { start: fromDay(start), end: fromDay(start + length) };
}

/** The window of the same length that ends the day before this one starts. */
export function previousWindow(window: DateWindow): DateWindow {
  const length = daysBetween(window.start, window.end) + 1;
  return { start: addDays(window.start, -length), end: addDays(window.start, -1) };
}

export function clampWindow(window: DateWindow, domain: DateWindow): DateWindow {
  const start = window.start < domain.start ? domain.start : window.start;
  const end = window.end > domain.end ? domain.end : window.end;
  return start <= end ? { start, end } : { start: domain.start, end: domain.end };
}

const short = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});
const monthYear = new Intl.DateTimeFormat("en-GB", {
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

export function formatDate(iso: string): string {
  return short.format(new Date(`${iso}T00:00:00Z`));
}

export function formatPeriod(period: string, interval: Interval): string {
  if (interval === "month") return monthYear.format(new Date(`${period}T00:00:00Z`));
  if (interval === "week") return `Week of ${formatDate(period)}`;
  return formatDate(period);
}

export function formatRange(window: DateWindow): string {
  if (window.start === window.end) return formatDate(window.start);
  return `${formatDate(window.start)} – ${formatDate(window.end)}`;
}

export function describeLength(days: number): string {
  if (days % 365 === 0 || days === 366) return days <= 366 ? "year" : `${Math.round(days / 365)} years`;
  if (days >= 28 && days <= 31) return "month";
  if (days % 7 === 0) return days === 7 ? "week" : `${days / 7} weeks`;
  return days === 1 ? "day" : `${days} days`;
}
