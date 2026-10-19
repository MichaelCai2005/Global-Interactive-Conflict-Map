import type { Facets } from "../api/types";
import { formatCount, SOURCE_DESCRIPTIONS, sourceLabel } from "../lib/format";
import { STORIES, type Story } from "../lib/stories";

interface Props {
  facets: Facets | undefined;
  onStory(story: Story): void;
  onClose(): void;
}

export function Welcome({ facets, onStory, onClose }: Props) {
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
        <h3>Start with a story</h3>
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
