import type { Filters } from "../state/dashboard";
import type { DateWindow } from "../lib/dates";
import { bboxToString } from "../lib/geo";
import type { Bbox } from "./types";

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "/api";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

type Params = Record<string, string | number | boolean | (string | number)[] | null | undefined>;

export function queryString(params: Params): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    for (const v of Array.isArray(value) ? value : [value]) q.append(key, String(v));
  }
  const text = q.toString();
  return text ? `?${text}` : "";
}

export async function request<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const response = await fetch(`${BASE}${path}`, {
    ...rest,
    headers: json === undefined ? rest.headers : { "Content-Type": "application/json", ...rest.headers },
    body: json === undefined ? rest.body : JSON.stringify(json),
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg?: string }) => d.msg).join("; ");
    } catch {
      // The body was not JSON; keep the status line.
    }
    throw new ApiError(response.status, message);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export interface Scope {
  filters: Filters;
  window?: DateWindow | null;
  bbox?: Bbox | null;
}

/** The backend's shared event filters (see EventFilters in backend/app/api/events.py). */
export function scopeParams({ filters, window, bbox }: Scope): Params {
  return {
    source: filters.sources,
    event_type: filters.types,
    violent: filters.violence === "all" ? null : filters.violence === "violent",
    country: filters.country,
    start: window?.start,
    end: window?.end,
    bbox: bbox ? bboxToString(bbox) : null,
  };
}
