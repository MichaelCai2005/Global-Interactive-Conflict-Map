import type { Interval, TimelineBucket } from "../api/types";
import { type DateWindow, nextPeriod, toDay } from "../lib/dates";
import { COLORS } from "../theme";

interface Props {
  buckets: TimelineBucket[];
  interval: Interval;
  domain: DateWindow;
  window: DateWindow;
  width?: number;
  height?: number;
}

/** Violent events over the timeline's range, with the current window marked. */
export function Sparkline({ buckets, interval, domain, window, width = 280, height = 32 }: Props) {
  const d0 = toDay(domain.start);
  const d1 = toDay(domain.end) + 1;
  const x = (day: number) => ((Math.min(Math.max(day, d0), d1) - d0) / (d1 - d0)) * width;
  const max = Math.max(1, ...buckets.map((b) => b.violent_events));
  let path = "";
  for (const b of buckets) {
    if (!b.violent_events) continue;
    const left = x(toDay(b.period));
    const w = Math.max(0.75, x(toDay(nextPeriod(b.period, interval))) - left);
    const h = Math.max(1, (b.violent_events / max) * (height - 2));
    path += `M${left.toFixed(1)},${height}h${w.toFixed(1)}v${(-h).toFixed(1)}h${(-w).toFixed(1)}Z`;
  }
  const wx0 = x(toDay(window.start));
  const wx1 = x(toDay(window.end) + 1);
  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden>
      <rect x={wx0} y={0} width={Math.max(1.5, wx1 - wx0)} height={height} fill={COLORS.ink} fillOpacity={0.1} />
      <line x1={0} x2={width} y1={height - 0.5} y2={height - 0.5} stroke={COLORS.grid} />
      <path d={path} fill={COLORS.violence} />
    </svg>
  );
}
