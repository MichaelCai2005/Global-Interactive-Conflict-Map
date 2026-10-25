import type { Facets } from "../api/types";
import { formatDate } from "../lib/dates";
import { formatCount, SOURCE_DESCRIPTIONS, sourceLabel } from "../lib/format";
import { STORIES, type Story } from "../lib/stories";

interface Props {
  facets: Facets | undefined;
  onTour(): void;
  onNow(): void;
  onStory(story: Story): void;
  onClose(): void;
}

export function Welcome({ facets, onTour, onNow, onStory, onClose }: Props) {
  const total = facets?.sources.reduce((sum, s) => sum + s.count, 0);
  return (
    <div className="welcome-backdrop" onClick={onClose}>
      <div
        className="welcome"
        role="dialog"
        aria-modal="true"
        aria-labelledby="welcome-title"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && onClose()}
      >
        <button className="drawer-close" onClick={onClose} aria-label="Close">
          ×
        </button>
        <h2 id="welcome-title">How conflicts develop, on a map and a timeline</h2>
        <p>
          {total ? `${formatCount(total)} events` : "Events"}
          {facets?.first_date && facets.last_date && ` from ${facets.first_date.slice(0, 4)} to ${facets.last_date.slice(0, 4)}`},
          merged from three sources and cleaned of duplicates.{" "}
          <span className="dot dot-violent" aria-hidden /> <strong>Violence</strong> is what happened;{" "}
          <span className="dot dot-signals" aria-hidden /> <strong>signals</strong> are the protests, threats and
          troop movements around it.
        </p>
        <ul className="sources">
          {facets?.sources.map((s) => (
            <li key={s.value}>
              <strong>{sourceLabel(s.value)}</strong> <span className="muted">{formatCount(s.count)}</span>
              <div className="muted small">{SOURCE_DESCRIPTIONS[s.value]}</div>
            </li>
          ))}
        </ul>
        <button className="primary tour-start" onClick={onTour}>
          New here? Take the one-minute tour
        </button>
        <ol className="how">
          <li>
            <strong>Drag the window</strong> on the timeline (or press play) to move through time. The map shows
            only the events inside it; older ones fade.
          </li>
          <li>
            <strong>Zoom the map</strong> into a region. The timeline and totals follow the map view, and dense
            areas break up from density circles into single events.
          </li>
          <li>
            <strong>Click an event</strong> for its details and the reports that match it, then watch the area
            or add a task.
          </li>
        </ol>
        <button className="story now-story" onClick={onNow} disabled={!facets?.last_date}>
          <span className="story-title">
            <span className="live-dot" aria-hidden /> See what's happening now
          </span>
          {facets?.last_date && <span className="muted small">The latest week, to {formatDate(facets.last_date)}</span>}
          <span className="small">
            This week's most reported violence, the deadliest recent fighting, and the countries whose risk is
            rising.
          </span>
        </button>
        <h3>Or start with a story from the past</h3>
        <div className="stories">
          {STORIES.map((s) => (
            <button key={s.id} className="story" onClick={() => onStory(s)}>
              <span className="story-title">{s.title}</span>
              <span className="muted small">{s.period}</span>
              <span className="small">{s.summary}</span>
            </button>
          ))}
        </div>
        <button className="ghost wide" onClick={onClose}>
          Explore on my own
        </button>
      </div>
    </div>
  );
}
