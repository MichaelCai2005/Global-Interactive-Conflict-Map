import type { Bbox } from "../api/types";

const CELL_SIZES = [8, 4, 2, 1, 0.5, 0.25, 0.1];

/**
 * Grid cell size in degrees for a map zoom level, aiming for cells about 24px across.
 * At zoom z the world is 512 * 2^z px wide, so 24px is 24 * 360 / (512 * 2^z) degrees.
 * Snapping to a fixed list keeps request URLs (and the cache) stable while zooming.
 */
export function cellSizeForZoom(zoom: number): number {
  const ideal = (24 * 360) / (512 * 2 ** zoom);
  return CELL_SIZES.reduce((best, size) =>
    Math.abs(Math.log(size / ideal)) < Math.abs(Math.log(best / ideal)) ? size : best,
  );
}

/**
 * Turns map bounds into a bbox filter. Returns null when the view covers (or wraps around)
 * the whole world, since then there is nothing to filter. Bounds are rounded outward to
 * 0.1 degree so small pans reuse cached responses.
 */
export function viewBbox(west: number, south: number, east: number, north: number): Bbox | null {
  if (east - west >= 300) return null;
  const wrap = (lon: number) => ((((lon + 180) % 360) + 360) % 360) - 180;
  const minLon = wrap(west);
  const maxLon = wrap(east);
  // A view across the antimeridian cannot be expressed as one min/max box.
  if (minLon > maxLon) return null;
  const down = (v: number) => Math.floor(v * 10) / 10;
  const up = (v: number) => Math.ceil(v * 10) / 10;
  return [
    Math.max(-180, down(minLon)),
    Math.max(-90, down(south)),
    Math.min(180, up(maxLon)),
    Math.min(90, up(north)),
  ];
}

export function bboxToString(bbox: Bbox): string {
  return bbox.join(",");
}

export function parseBbox(value: string | null | undefined): Bbox | null {
  if (!value) return null;
  const parts = value.split(",").map(Number);
  if (parts.length !== 4 || parts.some((n) => !Number.isFinite(n))) return null;
  const [minLon, minLat, maxLon, maxLat] = parts as Bbox;
  if (minLon > maxLon || minLat > maxLat) return null;
  return [minLon, minLat, maxLon, maxLat];
}

/** A short human label for an area, e.g. "48.5°N 37.8°E". */
export function describeBbox(bbox: Bbox): string {
  const lat = (bbox[1] + bbox[3]) / 2;
  const lon = (bbox[0] + bbox[2]) / 2;
  const fmt = (v: number, pos: string, neg: string) => `${Math.abs(v).toFixed(1)}°${v >= 0 ? pos : neg}`;
  return `Area around ${fmt(lat, "N", "S")} ${fmt(lon, "E", "W")}`;
}
