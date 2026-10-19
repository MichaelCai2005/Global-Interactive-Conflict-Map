import { useState } from "react";
import type { Interval, TimelineBucket } from "../api/types";
import { type DateWindow, addDays, clampWindow, daysBetween, formatRange } from "../lib/dates";
import { Timeline, TimelineTable } from "./Timeline";

interface Props {
  buckets: TimelineBucket[];
  interval: Interval;
  domain: DateWindow;
  full: DateWindow;
  window: DateWindow;
  loading: boolean;
  playing: boolean;
  speed: number;
  followView: boolean;
  zoomedIn: boolean;
  onWindow(window: DateWindow): void;
  onRange(range: DateWindow | null): void;
  onPlay(playing: boolean): void;
  onSpeed(speed: number): void;
  onFollowView(follow: boolean): void;
}

const LENGTHS = [
  { days: 7, label: "1W" },
  { days: 30, label: "1M" },
  { days: 91, label: "3M" },
  { days: 365, label: "1Y" },
];
const SPEEDS = [0.5, 1, 2, 4];

export function TimelineBar(props: Props) {
  const { domain, full, window, interval, buckets } = props;
  const [table, setTable] = useState(false);
  const length = daysBetween(window.start, window.end) + 1;
  const isFull = domain.start === full.start && domain.end === full.end;

  const setLength = (days: number) =>
    props.onWindow(clampWindow({ start: window.start, end: addDays(window.start, days - 1) }, domain));

  // Zooming the timeline keeps the window in view with room either side to see what came
  // before and after it.
  const zoomToWindow = () => {
    const pad = Math.max(length * 5, 45);
    props.onRange(clampWindow({ start: addDays(window.start, -pad), end: addDays(window.end, pad) }, full));
  };

  return (
    <section className="timeline-bar" aria-label="Timeline">
      <div className="timeline-controls">
        <button
          className="play"
          onClick={() => props.onPlay(!props.playing)}
          aria-label={props.playing ? "Pause" : "Play"}
          title={props.playing ? "Pause" : "Play: move the window forward step by step"}
        >
          {props.playing ? "❚❚" : "▶"}
        </button>
        <select
          value={props.speed}
          onChange={(e) => props.onSpeed(Number(e.target.value))}
          aria-label="Playback speed"
        >
          {SPEEDS.map((s) => (
            <option key={s} value={s}>
              {s}×
            </option>
          ))}
        </select>
        <strong className="window-label">{formatRange(window)}</strong>
        <div className="segmented small" role="group" aria-label="Window length">
          {LENGTHS.map((l) => (
            <button key={l.days} className={length === l.days ? "is-on" : ""} onClick={() => setLength(l.days)}>
              {l.label}
            </button>
          ))}
        </div>
        <span className="spacer" />
        <div className="segmented small" role="radiogroup" aria-label="Timeline counts">
          <button
            role="radio"
            aria-checked={props.followView}
            className={props.followView ? "is-on" : ""}
            onClick={() => props.onFollowView(true)}
            title="Timeline and totals count only events in the map view"
          >
            {props.zoomedIn ? "Map view" : "Map view (world)"}
          </button>
          <button
            role="radio"
            aria-checked={!props.followView}
            className={!props.followView ? "is-on" : ""}
            onClick={() => props.onFollowView(false)}
          >
            Everywhere
          </button>
        </div>
        {isFull ? (
          <button className="ghost small" onClick={zoomToWindow} title="Zoom the timeline in around the window">
            Zoom timeline
          </button>
        ) : (
          <button className="ghost small" onClick={() => props.onRange(null)}>
            Full range
          </button>
        )}
        <button className="ghost small" onClick={() => setTable(!table)} aria-pressed={table}>
          {table ? "Chart" : "Table"}
        </button>
      </div>
      {table ? (
        <TimelineTable buckets={buckets} interval={interval} />
      ) : (
        <Timeline
          buckets={buckets}
          interval={interval}
          domain={domain}
          window={window}
          loading={props.loading}
          onWindow={props.onWindow}
        />
      )}
    </section>
  );
}
