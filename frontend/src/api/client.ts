import type { Filters } from "../state/dashboard";
import type { DateWindow } from "../lib/dates";
import { bboxToString } from "../lib/geo";
import type { Bbox } from "./types";

export const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "/api";

// The sign-in token, for when the API is on another site (the frontend on GitHub Pages):
// browsers don't send cookies across sites, so it goes in the Authorization header. On one
// origin the httpOnly cookie does the same job and this stays empty.
const TOKEN_KEY = "cm_token";

export function sessionToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setSessionToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage is blocked (a private window); the sign-in lasts until the page closes.
  }
}

export function authHeaders(): Record<string, string> {
  const token = sessionToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

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
    headers: {
      ...authHeaders(),
      ...(json === undefined ? {} : { "Content-Type": "application/json" }),
      ...(rest.headers as Record<string, string> | undefined),
    },
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
  /** Only events GDELT first published at or after this ISO time. */
  reportedSince?: string | null;
}

/** The backend's shared event filters (see EventFilters in backend/app/api/events.py). */
export function scopeParams({ filters, window, bbox, reportedSince }: Scope): Params {
  return {
    source: filters.sources,
    event_type: filters.types,
    violent: filters.violence === "all" ? null : filters.violence === "violent",
    country: filters.country,
    start: window?.start,
    end: window?.end,
    bbox: bbox ? bboxToString(bbox) : null,
    reported_since: reportedSince,
  };
}
