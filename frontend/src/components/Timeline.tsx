import { type PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from "react";
import type { Interval, TimelineBucket } from "../api/types";
import {
  type DateWindow,
  addDays,
  clampWindow,
  daysBetween,
  formatPeriod,
  fromDay,
  nextPeriod,
  shiftWindow,
  stepFor,
  toDay,
} from "../lib/dates";
import { formatCompact, formatCount } from "../lib/format";
import { COLORS } from "../theme";

interface Props {
  buckets: TimelineBucket[];
  interval: Interval;
  domain: DateWindow;
  window: DateWindow;
  loading: boolean;
  onWindow(window: DateWindow): void;
}

const ROWS = [
  { key: "violent_events", label: "Violent events", color: COLORS.violence },
  { key: "signal_events", label: "Signal events", color: COLORS.signal },
  { key: "fatalities", label: "Deaths", color: COLORS.deaths },
] as const;

const GUTTER = 108;
const PAD_RIGHT = 12;
/** Rows grow past this to fill a taller timeline pane. */
const MIN_ROW_HEIGHT = 34;
const ROW_GAP = 8;
const AXIS = 20;
const EDGE = 7;

type Drag =
  | { mode: "move"; offset: number; origin: number }
  | { mode: "start" | "end" }
  | { mode: "create"; anchor: number; originX: number };

/**
 * Small multiples of violent events, signal events and deaths over time, one row each with
 * its own scale (they differ by orders of magnitude), and a draggable window across all three
 * that sets what the map shows.
 */
export function Timeline({ buckets, interval, domain, window, loading, onWindow }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 800, height: 0 });
  const [draft, setDraft] = useState<DateWindow | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const drag = useRef<Drag | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) =>
      setSize({ width: entry!.contentRect.width, height: entry!.contentRect.height }),
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const { width } = size;
  const rowHeight = Math.max(MIN_ROW_HEIGHT, Math.floor((size.height - AXIS) / ROWS.length) - ROW_GAP);
  const height = ROWS.length * (rowHeight + ROW_GAP) + AXIS;
  const d0 = toDay(domain.start);
  const d1 = toDay(domain.end) + 1;
  const plotWidth = Math.max(50, width - GUTTER - PAD_RIGHT);
  const x = (day: number) => GUTTER + ((day - d0) / (d1 - d0)) * plotWidth;
  const dayAt = (px: number) =>
    Math.round(d0 + ((Math.min(Math.max(px, GUTTER), GUTTER + plotWidth) - GUTTER) / plotWidth) * (d1 - d0));

  const visible = useMemo(
    () => buckets.filter((b) => b.period <= domain.end && nextPeriod(b.period, interval) > domain.start),
    [buckets, domain, interval],
  );

  const rows = useMemo(
    () =>
      ROWS.map((row, i) => {
        const max = Math.max(0, ...visible.map((b) => b[row.key]));
        const baseline = i * (rowHeight + ROW_GAP) + rowHeight;
        let path = "";
        if (max > 0) {
          for (const b of visible) {
            const value = b[row.key];
            if (!value) continue;
            const left = x(Math.max(toDay(b.period), d0));
            const right = x(Math.min(toDay(nextPeriod(b.period, interval)), d1));
            const span = right - left;
            const gap = span >= 6 ? 2 : span >= 3 ? 1 : 0;
            const w = Math.max(0.75, span - gap);
            // Keep tiny values visible as a one-pixel sliver rather than nothing.
            const h = Math.max(1, (value / max) * rowHeight);
            path += `M${left.toFixed(1)},${baseline}h${w.toFixed(1)}v${(-h).toFixed(1)}h${(-w).toFixed(1)}Z`;
          }
        }
        return { ...row, max, baseline, path };
      }),
    // x depends only on d0, d1 and plotWidth.
    [visible, d0, d1, plotWidth, interval, rowHeight],
  );

  const ticks = useMemo(() => axisTicks(domain, plotWidth), [domain, plotWidth]);
  const shown = draft ?? window;
  const wx0 = x(toDay(shown.start));
  const wx1 = x(toDay(shown.end) + 1);

  const localX = (e: ReactPointerEvent) => e.clientX - box.current!.getBoundingClientRect().left;

  function onPointerDown(e: ReactPointerEvent<SVGRectElement>) {
    const px = localX(e);
    const day = dayAt(px);
    e.currentTarget.setPointerCapture(e.pointerId);
    if (Math.abs(px - wx0) <= EDGE) drag.current = { mode: "start" };
    else if (Math.abs(px - wx1) <= EDGE) drag.current = { mode: "end" };
    else if (px > wx0 && px < wx1)
      drag.current = { mode: "move", offset: day - toDay(shown.start), origin: px };
    else drag.current = { mode: "create", anchor: day, originX: px };
    setHover(null);
  }

  function onPointerMove(e: ReactPointerEvent<SVGRectElement>) {
    const px = localX(e);
    const day = dayAt(px);
    const d = drag.current;
    if (!d) {
      const target = e.currentTarget;
      target.style.cursor =
        Math.abs(px - wx0) <= EDGE || Math.abs(px - wx1) <= EDGE
          ? "ew-resize"
          : px > wx0 && px < wx1
            ? "grab"
            : "crosshair";
      const index = visible.findIndex(
        (b) => toDay(b.period) <= day && toDay(nextPeriod(b.period, interval)) > day,
      );
      setHover(index === -1 ? null : index);
      return;
    }
    const current = draft ?? window;
    if (d.mode === "move") {
      const start = day - d.offset;
      setDraft(shiftWindow(current, start - toDay(current.start), domain));
    } else if (d.mode === "start") {
      setDraft({ start: fromDay(Math.min(day, toDay(current.end))), end: current.end });
    } else if (d.mode === "end") {
      setDraft({ start: current.start, end: fromDay(Math.max(day - 1, toDay(current.start))) });
    } else if (d.mode === "create" && Math.abs(px - d.originX) > 3) {
      const [a, b] = [Math.min(d.anchor, day), Math.max(d.anchor, day)];
      setDraft(clampWindow({ start: fromDay(a), end: fromDay(Math.max(a, b - 1)) }, domain));
    }
  }

  function onPointerUp(e: ReactPointerEvent<SVGRectElement>) {
    const d = drag.current;
    drag.current = null;
    if (draft) onWindow(draft);
    else if (d?.mode === "create") {
      // A click outside the window moves the window to centre on that day.
      const length = daysBetween(window.start, window.end);
      const start = dayAt(localX(e)) - Math.floor(length / 2);
      onWindow(shiftWindow(window, start - toDay(window.start), domain));
    }
    setDraft(null);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    const step = stepFor(window);
    const direction = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!direction) return;
    e.preventDefault();
    if (e.shiftKey) {
      const end = addDays(window.end, direction * step);
      if (end >= window.start) onWindow(clampWindow({ start: window.start, end }, domain));
    } else {
      onWindow(shiftWindow(window, direction * step, domain));
    }
  }

  const hovered = hover === null ? null : visible[hover];

  return (
    <div className={`timeline-chart${loading ? " is-loading" : ""}`} ref={box}>
      <svg width={width} height={height} role="img" aria-label="Events and deaths over time">
        {rows.map((row) => (
          <g key={row.key}>
            <line
              x1={GUTTER}
              x2={GUTTER + plotWidth}
              y1={row.baseline + 0.5}
              y2={row.baseline + 0.5}
              stroke={COLORS.grid}
            />
            <text x={0} y={row.baseline - rowHeight + 11} className="timeline-label">
              <tspan fill={row.color}>■</tspan> {row.label}
            </text>
            <text x={0} y={row.baseline - 2} className="timeline-max">
              peak {formatCompact(row.max)}
            </text>
            <path d={row.path} fill={row.color} />
          </g>
        ))}
        {ticks.map((t) => (
          <g key={t.day} transform={`translate(${x(t.day)},0)`}>
            <line y1={0} y2={height - AXIS} stroke={COLORS.grid} strokeOpacity={0.5} />
            <text y={height - 5} className="timeline-tick" textAnchor="middle">
              {t.label}
            </text>
          </g>
        ))}
        {/* Dim everything outside the window. */}
        <rect x={GUTTER} y={0} width={Math.max(0, wx0 - GUTTER)} height={height - AXIS} className="timeline-dim" />
        <rect x={wx1} y={0} width={Math.max(0, GUTTER + plotWidth - wx1)} height={height - AXIS} className="timeline-dim" />
        <rect
          x={wx0}
          y={0.5}
          width={Math.max(1.5, wx1 - wx0)}
          height={height - AXIS - 1}
          className="timeline-window"
        />
        <rect x={wx0 - 2} y={(height - AXIS) / 2 - 10} width={4} height={20} rx={2} className="timeline-grip" />
        <rect x={wx1 - 2} y={(height - AXIS) / 2 - 10} width={4} height={20} rx={2} className="timeline-grip" />
        {hovered && (
          <line
            x1={x(toDay(hovered.period))}
            x2={x(toDay(hovered.period))}
            y1={0}
            y2={height - AXIS}
            stroke={COLORS.ink}
            strokeOpacity={0.6}
          />
        )}
        <rect
          x={GUTTER}
          y={0}
          width={plotWidth}
          height={height}
          fill="transparent"
          tabIndex={0}
          role="slider"
          aria-label="Time window. Drag to move or resize. Arrow keys move it; Shift+arrows resize."
          aria-valuetext={`${window.start} to ${window.end}`}
          aria-valuemin={d0}
          aria-valuemax={d1}
          aria-valuenow={toDay(window.start)}
          className="timeline-hit"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={() => setHover(null)}
          onKeyDown={onKeyDown}
        />
      </svg>
      {hovered && (
        <div
          className="timeline-tooltip"
          style={{
            left: Math.min(x(toDay(hovered.period)) + 10, width - 190),
          }}
        >
          <div className="timeline-tooltip-title">{formatPeriod(hovered.period, interval)}</div>
          {ROWS.map((row) => (
            <div key={row.key} className="timeline-tooltip-row">
              <span className="swatch" style={{ background: row.color }} />
              <span>{row.label}</span>
              <span className="num">{formatCount(hovered[row.key])}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function TimelineTable({ buckets, interval }: { buckets: TimelineBucket[]; interval: Interval }) {
  return (
    <div className="timeline-table">
      <table>
        <thead>
          <tr>
            <th>Period</th>
            {ROWS.map((r) => (
              <th key={r.key} className="num">
                {r.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {buckets.map((b) => (
            <tr key={b.period}>
              <td>{formatPeriod(b.period, interval)}</td>
              {ROWS.map((r) => (
                <td key={r.key} className="num">
                  {formatCount(b[r.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface Tick {
  day: number;
  label: string;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Year, month or day ticks, as many as fit at about 70px apart. */
export function axisTicks(domain: DateWindow, plotWidth: number): Tick[] {
  const spanDays = daysBetween(domain.start, domain.end) + 1;
  const maxTicks = Math.max(2, Math.floor(plotWidth / 70));
  const [y0, m0] = domain.start.split("-").map(Number) as [number, number];
  const [y1] = domain.end.split("-").map(Number) as [number];
  const inside = (iso: string) => iso >= domain.start && iso <= domain.end;
  const ticks: Tick[] = [];

  const yearStep = [1, 2, 5, 10, 20].find((s) => spanDays / (365 * s) <= maxTicks);
  if (spanDays > 365 * 2.5 && yearStep) {
    for (let y = Math.ceil(y0 / yearStep) * yearStep; y <= y1; y += yearStep) {
      const iso = `${y}-01-01`;
      if (inside(iso)) ticks.push({ day: toDay(iso), label: String(y) });
    }
    return ticks;
  }
  const monthStep = [1, 2, 3, 6].find((s) => spanDays / (30.4 * s) <= maxTicks);
  if (spanDays > 70 && monthStep) {
    for (let i = 0; ; i++) {
      const total = (m0 - 1) + i;
      const y = y0 + Math.floor(total / 12);
      const m = total % 12;
      const iso = `${y}-${String(m + 1).padStart(2, "0")}-01`;
      if (iso > domain.end) break;
      if (m % monthStep !== 0 || !inside(iso)) continue;
      ticks.push({ day: toDay(iso), label: m === 0 ? String(y) : MONTHS[m]! });
    }
    return ticks;
  }
  const dayStep = [1, 2, 7, 14].find((s) => spanDays / s <= maxTicks) ?? 14;
  for (let d = toDay(domain.start); d <= toDay(domain.end); d += dayStep) {
    const iso = fromDay(d);
    const [, m, day] = iso.split("-").map(Number) as [number, number, number];
    ticks.push({ day: d, label: `${day} ${MONTHS[m - 1]}` });
  }
  return ticks;
}
