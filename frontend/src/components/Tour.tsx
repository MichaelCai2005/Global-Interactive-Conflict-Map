import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Panel } from "../state/dashboard";

/**
 * A guided tour: each step dims the page except one part of it, found by its data-tour
 * attribute, and explains what that part does. A step with no target, or whose target is
 * hidden (a closed pane, a signed-out-only button), shows its card in the middle instead.
 */
export interface TourStep {
  /** The data-tour value of the element to point at. */
  target?: string;
  /** The side-panel tab to show during the step; steps without one show the tab the tour began on. */
  panel?: Panel;
  title: string;
  body: ReactNode;
}

export const TOUR_STEPS: TourStep[] = [
  {
    title: "A one-minute tour",
    body: (
      <>
        <p>
          This map shows armed conflict around the world: <span className="dot dot-violent" aria-hidden />{" "}
          <strong>violence</strong> that happened, and <span className="dot dot-signals" aria-hidden />{" "}
          <strong>signals</strong> around it, like protests, threats and troop movements.
        </p>
        <p>Here are the four things you'll use most. The rest can wait until you want it.</p>
      </>
    ),
  },
  {
    target: "map",
    title: "The map",
    body: (
      <>
        <p>
          Each dot is an event. Bigger dots had more deaths, and the legend in the corner explains the colours.
        </p>
        <p>
          Scroll or pinch to zoom in on a region. <strong>Click a dot</strong> to see what happened and the news
          reports about it.
        </p>
      </>
    ),
  },
  {
    target: "timeline",
    title: "The timeline",
    body: (
      <>
        <p>
          The highlighted <strong>window</strong> is the stretch of time the map shows. Drag it to move through time,
          or press <strong>play</strong> to watch events unfold.
        </p>
        <p>
          <strong>1W, 1M, 3M, 1Y</strong> set the window's length, and <strong>Latest</strong> jumps back to the
          newest data.
        </p>
      </>
    ),
  },
  {
    target: "filters",
    title: "Choose what to show",
    body: (
      <p>
        Show only violence or only signals, or pick one country. <strong>More filters</strong> chooses data sources
        and event types.
      </p>
    ),
  },
  {
    target: "sidebar",
    panel: "now",
    title: "What's happening now",
    body: (
      <p>
        The <strong>Now</strong> tab shows the latest week: the news, the deadliest recent fighting, and countries
        where risk is rising. Click anything to fly the map to it.
      </p>
    ),
  },
  {
    target: "discover",
    title: "Find the rest at your own pace",
    body: (
      <>
        <p>
          <strong>Things to try</strong> suggests one new thing at a time, such as risk scores, replays of past
          conflicts and research boards. It ticks each one off as you use it.
        </p>
        <p>
          <strong>Stories &amp; help</strong> brings back this tour.
        </p>
      </>
    ),
  },
];

interface Props {
  steps?: TourStep[];
  /** The tab the tour began on, shown again by steps that don't name one and after the tour. */
  startPanel: Panel;
  onPanel(panel: Panel): void;
  onClose(): void;
}

interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

const GAP = 12;
const PAD = 6;
const CARD_WIDTH = 340;

export function Tour({ steps = TOUR_STEPS, startPanel, onPanel, onClose }: Props) {
  const [index, setIndex] = useState(0);
  const step = steps[index]!;
  const last = index === steps.length - 1;
  const box = useTargetBox(step.target);
  const card = useRef<HTMLDivElement>(null);
  const [cardHeight, setCardHeight] = useState(220);
  const viewport = useViewport();

  const panel = step.panel ?? startPanel;
  // onPanel is a new function every render; only a change of tab matters.
  useEffect(() => onPanel(panel), [panel]);

  const close = () => {
    onPanel(startPanel);
    onClose();
  };
  const next = () => (last ? close() : setIndex(index + 1));
  const back = () => setIndex(Math.max(0, index - 1));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") return close();
      // Arrow keys belong to whatever has focus, such as the timeline, unless that is the card.
      const focus = document.activeElement;
      if (focus !== document.body && !card.current?.contains(focus)) return;
      if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") back();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // A single step points at one control, so using that control is the answer: pressing it
  // closes the pointer and lets the press through.
  const pointer = steps.length === 1 ? step.target : undefined;
  useEffect(() => {
    if (!pointer) return;
    const onPress = (e: PointerEvent) => {
      if (document.querySelector(`[data-tour="${pointer}"]`)?.contains(e.target as Node)) close();
    };
    window.addEventListener("pointerdown", onPress, true);
    return () => window.removeEventListener("pointerdown", onPress, true);
  });

  // Move focus to the card so screen readers announce each step.
  useLayoutEffect(() => {
    card.current?.focus({ preventScroll: true });
    if (card.current) setCardHeight(card.current.offsetHeight);
  }, [index]);

  const hole = box && padWithin(box, viewport);
  const position = placeCard(hole, cardHeight, viewport);

  return (
    <div className="tour" role="presentation">
      {/* Catches clicks everywhere except the highlighted part, which stays usable. */}
      <div
        className={`tour-blocker${hole ? "" : " is-dim"}`}
        style={hole ? { clipPath: cutout(hole, viewport) } : undefined}
      />
      {hole && <div className="tour-hole" style={hole} />}
      <div
        ref={card}
        className="tour-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        tabIndex={-1}
        style={{ ...position, width: Math.min(CARD_WIDTH, viewport.width - 32) }}
      >
        {/* A single step is a pointer at one control, not a tour. */}
        {steps.length > 1 && (
          <div className="tour-progress small muted">
            Step {index + 1} of {steps.length}
            <span className="tour-dots" aria-hidden>
              {steps.map((_, i) => (
                <span key={i} className={i === index ? "is-on" : i < index ? "is-done" : ""} />
              ))}
            </span>
          </div>
        )}
        <h2 id="tour-title">{step.title}</h2>
        <div className="tour-body">{step.body}</div>
        <div className="tour-actions">
          {steps.length > 1 && (
            <button className="link-button small" onClick={close}>
              {last ? "Close" : "Skip tour"}
            </button>
          )}
          <span className="spacer" />
          {index > 0 && (
            <button className="ghost" onClick={back}>
              Back
            </button>
          )}
          <button className="primary" onClick={next}>
            {steps.length === 1 ? "Got it" : last ? "Finish" : index === 0 ? "Start" : "Next"}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Where the target sits on screen, followed as the layout settles, scrolls or resizes. */
function useTargetBox(target: string | undefined): Box | null {
  const [box, setBox] = useState<Box | null>(null);
  useEffect(() => {
    if (!target) {
      setBox(null);
      return;
    }
    const find = () => document.querySelector<HTMLElement>(`[data-tour="${target}"]`);
    // On narrow screens the page scrolls, so bring the target into view first.
    find()?.scrollIntoView?.({ block: "center", behavior: "smooth" });
    let frame = 0;
    const measure = () => {
      const r = find()?.getBoundingClientRect();
      const next = r && r.width > 0 && r.height > 0 ? clip(r) : null;
      setBox((prev) => (sameBox(prev, next) ? prev : next));
      frame = requestAnimationFrame(measure);
    };
    measure();
    return () => cancelAnimationFrame(frame);
  }, [target]);
  return box;
}

function useViewport() {
  const read = () => ({ width: window.innerWidth, height: window.innerHeight });
  const [size, setSize] = useState(read);
  useEffect(() => {
    const update = () => setSize(read());
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return size;
}

/** Keeps a box within the viewport, so a target taller than the screen still gets a card beside it. */
function clip(r: DOMRect): Box {
  const top = Math.max(r.top, 0);
  const left = Math.max(r.left, 0);
  const bottom = Math.min(r.bottom, window.innerHeight);
  const right = Math.min(r.right, window.innerWidth);
  return { top, left, width: Math.max(right - left, 0), height: Math.max(bottom - top, 0) };
}

/** Grows the box by PAD on each side, but keeps its outline on screen for targets at the edge. */
function padWithin(box: Box, viewport: { width: number; height: number }): Box {
  const top = Math.max(box.top - PAD, 2);
  const left = Math.max(box.left - PAD, 2);
  const bottom = Math.min(box.top + box.height + PAD, viewport.height - 2);
  const right = Math.min(box.left + box.width + PAD, viewport.width - 2);
  return { top, left, width: right - left, height: bottom - top };
}

function sameBox(a: Box | null, b: Box | null): boolean {
  if (!a || !b) return a === b;
  return (
    Math.abs(a.top - b.top) < 1 &&
    Math.abs(a.left - b.left) < 1 &&
    Math.abs(a.width - b.width) < 1 &&
    Math.abs(a.height - b.height) < 1
  );
}

/** Puts the card below, above, right or left of the hole, whichever fits first; inside it if none do. */
function placeCard(
  hole: Box | null,
  height: number,
  viewport: { width: number; height: number },
): { top: number; left: number } {
  const width = Math.min(CARD_WIDTH, viewport.width - 32);
  const clampLeft = (x: number) => Math.min(Math.max(x, 16), viewport.width - width - 16);
  const clampTop = (y: number) => Math.min(Math.max(y, 16), viewport.height - height - 16);
  if (!hole) return { top: clampTop((viewport.height - height) / 2), left: clampLeft((viewport.width - width) / 2) };

  const centerX = hole.left + hole.width / 2 - width / 2;
  const centerY = hole.top + hole.height / 2 - height / 2;
  const below = hole.top + hole.height + GAP;
  if (below + height <= viewport.height - 16) return { top: below, left: clampLeft(centerX) };
  const above = hole.top - GAP - height;
  if (above >= 16) return { top: above, left: clampLeft(centerX) };
  const right = hole.left + hole.width + GAP;
  if (right + width <= viewport.width - 16) return { top: clampTop(centerY), left: right };
  const left = hole.left - GAP - width;
  if (left >= 16) return { top: clampTop(centerY), left };
  // A big target such as the map: sit in its lower left corner.
  return { top: clampTop(hole.top + hole.height - height - 24), left: clampLeft(hole.left + 24) };
}

/** A clip path covering the whole viewport except the hole. */
function cutout(hole: Box, viewport: { width: number; height: number }): string {
  const { top, left, width, height } = hole;
  return (
    `path(evenodd, "M0 0H${viewport.width}V${viewport.height}H0Z ` +
    `M${left} ${top}h${width}v${height}h${-width}Z")`
  );
}
