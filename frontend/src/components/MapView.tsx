import type { ExpressionSpecification } from "@maplibre/maplibre-gl-style-spec";
import type { FeatureCollection } from "geojson";
import {
  type GeoJSONSource,
  type MapGeoJSONFeature,
  type MapLayerMouseEvent,
  MapLibreMap,
  NavigationControl,
  Popup,
  setWorkerUrl,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { type Ref, useEffect, useImperativeHandle, useRef, useState } from "react";
import type { Bbox, CellProps, MapLayer, PointProps } from "../api/types";
import { type DateWindow, formatDate, toDay } from "../lib/dates";
import { eventTypeLabel, formatCount, plural, sourceLabel } from "../lib/format";
import { viewBbox } from "../lib/geo";
import { BOARD_STYLE_COLORS, KIND_LABELS } from "../board/style";
import type { Camera } from "../state/dashboard";
import { COLORS } from "../theme";

// MapLibre finds its worker next to its own module file, which bundlers move; let Vite
// bundle the worker and say where it ended up.
setWorkerUrl(workerUrl);

const STYLE_URL =
  (import.meta.env.VITE_MAP_STYLE as string | undefined) ??
  "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

export interface MapHandle {
  fitBbox(bbox: Bbox): void;
  flyTo(lon: number, lat: number, zoom?: number): void;
}

interface Props {
  ref?: Ref<MapHandle>;
  initialCamera: Camera;
  layer: MapLayer | undefined;
  window: DateWindow | null;
  selected: { lon: number; lat: number } | null;
  /** Country risk scores; when given, the map shows them instead of events. */
  risk: FeatureCollection | null;
  riskSelected: string | null;
  /** A link board (see board/), drawn over the events up to the window's end. */
  board?: FeatureCollection | null;
  boardSelected?: number | null;
  onMove(camera: Camera, bbox: Bbox | null): void;
  onSelect(eventId: number): void;
  onRiskSelect(iso3: string): void;
  onBoardSelect?(nodeId: number): void;
}

const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

// Radius grows with the square root of deaths, so area is roughly proportional to them.
const POINT_RADIUS: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["sqrt", ["get", "deaths"]],
  0, 3.5,
  3, 6,
  10, 10,
  30, 18,
  100, 28,
];

// Risk scores (0-100) use one hue, violet, that no event or risk-component color uses:
// dim and small for low scores, bright and large for high ones.
const RISK_COLOR: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["get", "score"],
  0, "#3b3470",
  25, "#5a4fb0",
  50, "#8076e0",
  75, "#aba3f0",
  100, "#dcd8ff",
];
const RISK_RADIUS: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["sqrt", ["get", "score"]],
  1, 4,
  3, 8,
  5.5, 14,
  7.75, 21,
  10, 30,
];

export function MapView({
  ref,
  initialCamera,
  layer,
  window,
  selected,
  risk,
  riskSelected,
  board = null,
  boardSelected = null,
  onMove,
  onSelect,
  onRiskSelect,
  onBoardSelect,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);
  const [styleError, setStyleError] = useState(false);
  // Handlers change every render; the map's listeners read them through a ref.
  const handlers = useRef({ onMove, onSelect, onRiskSelect, onBoardSelect });
  handlers.current = { onMove, onSelect, onRiskSelect, onBoardSelect };

  useImperativeHandle(ref, () => ({
    fitBbox(bbox) {
      mapRef.current?.fitBounds(
        [
          [bbox[0], bbox[1]],
          [bbox[2], bbox[3]],
        ],
        { padding: 40, duration: 1200, maxZoom: 9 },
      );
    },
    flyTo(lon, lat, zoom) {
      const map = mapRef.current;
      map?.flyTo({ center: [lon, lat], zoom: zoom ?? Math.max(map.getZoom(), 7), duration: 1200 });
    },
  }));

  useEffect(() => {
    const map = new MapLibreMap({
      container: container.current!,
      style: STYLE_URL,
      center: [initialCamera.lon, initialCamera.lat],
      zoom: initialCamera.zoom,
      minZoom: 1,
      maxZoom: 14,
      attributionControl: { compact: true },
      renderWorldCopies: false,
    });
    mapRef.current = map;
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");

    const report = () => {
      const c = map.getCenter();
      const b = map.getBounds();
      handlers.current.onMove(
        { lon: c.lng, lat: c.lat, zoom: map.getZoom() },
        viewBbox(b.getWest(), b.getSouth(), b.getEast(), b.getNorth()),
      );
    };
    map.on("moveend", report);
    map.on("error", (e) => {
      if (!map.isStyleLoaded() && /style/i.test(String(e.error?.message))) setStyleError(true);
    });

    map.on("load", () => {
      // Draw events beneath the basemap's place names so labels stay readable.
      const firstLabel = map.getStyle().layers.find((l) => l.type === "symbol")?.id;
      map.addSource("events", { type: "geojson", data: EMPTY });
      map.addSource("selection", { type: "geojson", data: EMPTY });
      map.addSource("risk", { type: "geojson", data: EMPTY });

      map.addLayer(
        {
          id: "cells",
          type: "circle",
          source: "events",
          layout: { visibility: "none" },
          paint: {
            "circle-color": shareColor(),
            "circle-opacity": 0.7,
            "circle-stroke-color": COLORS.surface,
            "circle-stroke-width": 1,
          },
        },
        firstLabel,
      );
      map.addLayer(
        {
          id: "points",
          type: "circle",
          source: "events",
          filter: ["!=", ["get", "precision"], "country"],
          paint: {
            "circle-color": ["case", ["get", "violent"], COLORS.violence, COLORS.signal],
            "circle-radius": POINT_RADIUS,
            "circle-stroke-color": COLORS.surface,
            "circle-stroke-width": 1,
          },
        },
        firstLabel,
      );
      // Events located only to a country are drawn hollow at the country's centre: the
      // dot says "somewhere in this country", not "here".
      map.addLayer(
        {
          id: "points-country",
          type: "circle",
          source: "events",
          filter: ["==", ["get", "precision"], "country"],
          paint: {
            "circle-color": "rgba(0,0,0,0)",
            "circle-radius": POINT_RADIUS,
            "circle-stroke-color": ["case", ["get", "violent"], COLORS.violence, COLORS.signal],
            "circle-stroke-width": 1.5,
          },
        },
        firstLabel,
      );
      map.addLayer(
        {
          id: "risk",
          type: "circle",
          source: "risk",
          layout: { visibility: "none", "circle-sort-key": ["get", "score"] },
          paint: {
            "circle-color": RISK_COLOR,
            "circle-radius": RISK_RADIUS,
            "circle-opacity": 0.8,
            // A surge alarm gets an orange ring; the legend names it, so color is not alone.
            "circle-stroke-color": ["case", ["==", ["get", "alarm"], true], COLORS.alarm, COLORS.surface],
            "circle-stroke-width": ["case", ["==", ["get", "alarm"], true], 2.5, 1],
          },
        },
        firstLabel,
      );
      map.addLayer({
        id: "risk-selected",
        type: "circle",
        source: "risk",
        filter: ["==", ["get", "iso3"], ""],
        layout: { visibility: "none" },
        paint: {
          "circle-color": "rgba(0,0,0,0)",
          "circle-radius": ["+", RISK_RADIUS, 4],
          "circle-stroke-color": COLORS.ink,
          "circle-stroke-width": 2.5,
        },
      });
      addBoardLayers(map, firstLabel);
      map.addLayer({
        id: "selection",
        type: "circle",
        source: "selection",
        paint: {
          "circle-radius": 12,
          "circle-color": "rgba(0,0,0,0)",
          "circle-stroke-color": COLORS.ink,
          "circle-stroke-width": 2.5,
        },
      });
      setReady(true);
      report();
    });

    const popup = new Popup({ closeButton: false, closeOnClick: false, offset: 10 });
    const hover = (e: MapLayerMouseEvent) => {
      const feature = e.features?.[0];
      if (!feature) return;
      map.getCanvas().style.cursor = "pointer";
      popup.setLngLat(e.lngLat).setDOMContent(tooltip(feature)).addTo(map);
    };
    const leave = () => {
      map.getCanvas().style.cursor = "";
      popup.remove();
    };
    for (const id of ["points", "points-country", "cells", "risk", "board-nodes"]) {
      map.on("mousemove", id, hover);
      map.on("mouseleave", id, leave);
    }
    map.on("click", "board-nodes", (e) => {
      const nodeId = e.features?.[0]?.properties?.node_id;
      if (typeof nodeId === "number") handlers.current.onBoardSelect?.(nodeId);
    });
    const pick = (e: MapLayerMouseEvent) => {
      const id = e.features?.[0]?.properties?.id;
      if (typeof id === "number") handlers.current.onSelect(id);
    };
    map.on("click", "points", pick);
    map.on("click", "points-country", pick);
    map.on("click", "risk", (e) => {
      const iso3 = e.features?.[0]?.properties?.iso3;
      if (typeof iso3 === "string") handlers.current.onRiskSelect(iso3);
    });
    map.on("click", "cells", (e) => {
      const geometry = e.features?.[0]?.geometry;
      if (geometry?.type !== "Point") return;
      const [lon, lat] = geometry.coordinates as [number, number];
      map.easeTo({ center: [lon, lat], zoom: map.getZoom() + 2 });
    });

    return () => {
      popup.remove();
      map.remove();
      mapRef.current = null;
    };
    // The map is created once; later camera changes come from the user or the handle.
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const riskMode = risk !== null;
    const show = (id: string, visible: boolean) =>
      map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
    show("risk", riskMode);
    show("risk-selected", riskMode);
    if (riskMode) (map.getSource("risk") as GeoJSONSource).setData(risk);
    const grid = layer?.mode === "grid";
    show("cells", !riskMode && grid);
    show("points", !riskMode && !grid);
    show("points-country", !riskMode && !grid);
  }, [ready, risk, layer?.mode]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    map.setFilter("risk-selected", ["==", ["get", "iso3"], riskSelected ?? ""]);
  }, [ready, riskSelected]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource("board") as GeoJSONSource).setData(board ?? EMPTY);
    for (const id of BOARD_LAYERS) map.setLayoutProperty(id, "visibility", board ? "visible" : "none");
  }, [ready, board]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    // The board as it stood at the window's end: items appear as the timeline plays, and
    // items from before the window fade. Places and groups have no date and always show.
    const end = window ? toDay(window.end) : Number.MAX_SAFE_INTEGER;
    const start = window ? toDay(window.start) : 0;
    const shown: ExpressionSpecification = [
      "any",
      ["==", ["typeof", ["get", "day"]], "null"],
      ["<=", ["to-number", ["get", "day"], 0], end],
    ];
    const fade: ExpressionSpecification = [
      "case",
      ["==", ["typeof", ["get", "day"]], "null"],
      1,
      ["<", ["to-number", ["get", "day"], 0], start],
      0.45,
      1,
    ];
    map.setFilter("board-links-accepted", ["all", ["has", "link_id"], ["==", ["get", "status"], "accepted"], shown]);
    map.setFilter("board-links-suggested", ["all", ["has", "link_id"], ["==", ["get", "status"], "suggested"], shown]);
    map.setFilter("board-tracks", ["all", ["has", "node_id"], ["==", ["geometry-type"], "LineString"], shown]);
    map.setFilter("board-nodes", ["all", ["has", "node_id"], ["==", ["geometry-type"], "Point"], shown]);
    map.setFilter("board-labels", [
      "all",
      ["has", "node_id"],
      ["==", ["geometry-type"], "Point"],
      ["in", ["get", "kind"], ["literal", ["article", "place", "actor", "claim", "note"]]],
      shown,
    ]);
    map.setPaintProperty("board-nodes", "circle-opacity", fade);
    map.setPaintProperty("board-links-suggested", "line-opacity", ["*", 0.75, fade]);
  }, [ready, window]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const isSelected: ExpressionSpecification = ["==", ["get", "node_id"], boardSelected ?? -1];
    map.setPaintProperty("board-nodes", "circle-stroke-color", ["case", isSelected, COLORS.ink, COLORS.surface]);
    map.setPaintProperty("board-nodes", "circle-stroke-width", ["case", isSelected, 3, 1]);
  }, [ready, boardSelected]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !layer) return;
    (map.getSource("events") as GeoJSONSource).setData(layer.features);
    if (layer.mode === "grid") {
      const max = Math.max(1, ...layer.features.features.map((f) => f.properties.events));
      map.setPaintProperty("cells", "circle-radius", [
        "+",
        3,
        ["*", 24, ["sqrt", ["/", ["get", "events"], max]]],
      ]);
    }
  }, [ready, layer]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !window) return;
    // Older events in the window fade, so the newest activity stands out during playback.
    const start = toDay(window.start);
    const end = Math.max(toDay(window.end), start + 1);
    // With a board open, events are background and stay dim.
    const [low, high] = board ? [0.12, 0.35] : [0.3, 0.95];
    const opacity: ExpressionSpecification = ["interpolate", ["linear"], ["get", "day"], start, low, end, high];
    map.setPaintProperty("points", "circle-opacity", opacity);
    map.setPaintProperty("points-country", "circle-stroke-opacity", opacity);
    map.setPaintProperty("cells", "circle-opacity", board ? 0.25 : 0.7);
  }, [ready, window, board]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource("selection") as GeoJSONSource).setData(
      selected
        ? {
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                geometry: { type: "Point", coordinates: [selected.lon, selected.lat] },
                properties: {},
              },
            ],
          }
        : EMPTY,
    );
  }, [ready, selected]);

  return (
    <div className="map" ref={container} aria-label="Map of events">
      {styleError && (
        <div className="map-notice">
          The basemap could not load (no connection to the tile server?). Events still draw
          on a blank background.
        </div>
      )}
    </div>
  );
}

const BOARD_LAYERS = ["board-links-suggested", "board-links-accepted", "board-tracks", "board-nodes", "board-labels"];

const BOARD_COLOR = [
  "match",
  ["get", "style"],
  ...Object.entries(BOARD_STYLE_COLORS).flat(),
  BOARD_STYLE_COLORS.note!,
] as unknown as ExpressionSpecification;

/** Board items above the events: links, flight tracks, points by kind, and names. */
function addBoardLayers(map: MapLibreMap, beforeLabel: string | undefined) {
  map.addSource("board", { type: "geojson", data: EMPTY });
  const hidden = { visibility: "none" as const };
  map.addLayer({
    id: "board-links-suggested",
    type: "line",
    source: "board",
    layout: hidden,
    paint: { "line-color": "#8d99ae", "line-width": 1.5, "line-dasharray": [3, 2] },
  });
  map.addLayer({
    id: "board-links-accepted",
    type: "line",
    source: "board",
    layout: hidden,
    paint: { "line-color": "#e9ecef", "line-width": 2.5 },
  });
  map.addLayer({
    id: "board-tracks",
    type: "line",
    source: "board",
    layout: hidden,
    paint: { "line-color": BOARD_COLOR, "line-width": 2.5 },
  });
  map.addLayer({
    id: "board-nodes",
    type: "circle",
    source: "board",
    layout: hidden,
    paint: {
      "circle-color": BOARD_COLOR,
      "circle-radius": ["match", ["get", "kind"], "article", 9, "place", 7, "actor", 7, 5.5],
      "circle-stroke-color": COLORS.surface,
      "circle-stroke-width": 1,
    },
  });
  // Names use the basemap's own font, so they need no extra font files.
  const font = beforeLabel ? (map.getLayoutProperty(beforeLabel, "text-font") as string[] | undefined) : undefined;
  map.addLayer({
    id: "board-labels",
    type: "symbol",
    source: "board",
    layout: {
      ...hidden,
      "text-field": ["get", "label"],
      ...(font ? { "text-font": font } : {}),
      "text-size": ["match", ["get", "kind"], "article", 13, 11.5],
      "text-offset": [0, 1.1],
      "text-anchor": "top",
      "text-max-width": 14,
      "text-optional": true,
    },
    paint: { "text-color": COLORS.ink, "text-halo-color": COLORS.surface, "text-halo-width": 1.5 },
  });
}

/** Grid cells run from blue (all signals) through grey (mixed) to orange (all violence). */
function shareColor(): ExpressionSpecification {
  return [
    "interpolate",
    ["linear"],
    ["/", ["get", "violent"], ["max", 1, ["get", "events"]]],
    0, COLORS.signal,
    0.5, COLORS.neutral,
    1, COLORS.violence,
  ];
}

function tooltip(feature: MapGeoJSONFeature): HTMLElement {
  const el = document.createElement("div");
  el.className = "map-tooltip";
  const line = (text: string, className?: string) => {
    const div = document.createElement("div");
    div.textContent = text;
    if (className) div.className = className;
    el.append(div);
  };
  if ("node_id" in feature.properties) {
    const p = feature.properties as { label: string; kind: string; status: string };
    line(p.label, "map-tooltip-title");
    line(`${KIND_LABELS[p.kind] ?? p.kind} · ${p.status}`);
    line("Click to find it on the board", "map-tooltip-hint");
  } else if ("score" in feature.properties) {
    const p = feature.properties as { name: string; score: number; change?: number | null; trend?: string | null; alarm?: boolean };
    line(p.name, "map-tooltip-title");
    const change =
      typeof p.change !== "number" ? "" : p.change === 0 ? ", same as last week" : ` (${p.change > 0 ? "+" : ""}${p.change} on last week)`;
    line(`Risk ${p.score} / 100${change}`);
    if (p.trend) line(`Trend: ${p.trend}`);
    if (p.alarm === true) line("Surge alarm: far more violence than usual here", "map-tooltip-alarm");
    line("Click to see why", "map-tooltip-hint");
  } else if ("events" in feature.properties) {
    const p = feature.properties as CellProps;
    line(plural(p.events, "event"), "map-tooltip-title");
    line(`${formatCount(p.violent)} violent · ${formatCount(p.signals)} signals`);
    if (p.deaths) line(plural(p.deaths, "death"));
    line("Click to zoom in", "map-tooltip-hint");
  } else {
    const p = feature.properties as PointProps;
    line(eventTypeLabel(p.type), "map-tooltip-title");
    line(`${formatDate(p.date)} · ${sourceLabel(p.source)}`);
    if (p.deaths) line(plural(p.deaths, "death"));
    if (p.precision === "country") line("Location known only to country level", "map-tooltip-hint");
    line("Click for details", "map-tooltip-hint");
  }
  return el;
}
