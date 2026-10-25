import { type ReactNode, type RefObject, useEffect, useState } from "react";
import {
  type LayoutStorage,
  type PanelImperativeHandle,
  type PanelSize,
  useDefaultLayout,
  usePanelRef,
} from "react-resizable-panels";
import { PanelBottomClose, PanelBottomOpen, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/** Below this width the panes stack and the page scrolls, as on a phone. */
const WIDE = "(min-width: 901px)";

/** A pane that can be closed and reopened: the side panel or the timeline. */
export interface Pane {
  ref: RefObject<PanelImperativeHandle | null>;
  open: boolean;
  onResize(size: PanelSize): void;
  toggle(open?: boolean): void;
}

function usePane(): Pane {
  const ref = usePanelRef();
  const [open, setOpen] = useState(true);
  return {
    ref,
    open,
    onResize: (size) => setOpen(size.inPixels > 0),
    toggle: (show = !open) => (show ? ref.current?.expand() : ref.current?.collapse()),
  };
}

export function usePanes() {
  const wide = useMediaQuery(WIDE);
  return { wide, sidebar: usePane(), timeline: usePane() };
}
export type Panes = ReturnType<typeof usePanes>;

// Sizes are remembered per browser; storage can be unavailable (private windows), and then
// the default layout just comes back each visit.
const storage: LayoutStorage = {
  getItem(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      // Not remembered; nothing else depends on it.
    }
  },
};

interface Props {
  panes: Panes;
  sidebar: ReactNode;
  map: ReactNode;
  timeline: ReactNode;
}

/**
 * The side panel, map and timeline. On a wide screen each edge between them can be dragged,
 * and the side panel and timeline can be closed, by button or by dragging them shut.
 */
export function Workspace({ panes, sidebar, map, timeline }: Props) {
  const rows = useDefaultLayout({ id: "conflict-map:layout-rows", storage });
  const columns = useDefaultLayout({ id: "conflict-map:layout-columns", storage });

  if (!panes.wide) {
    return (
      <div className="stacked">
        {map}
        {timeline}
        {sidebar}
      </div>
    );
  }
  return (
    <ResizablePanelGroup id="workspace-rows" orientation="vertical" className="workspace" {...rows}>
      <ResizablePanel id="pane-upper" className="pane">
        <ResizablePanelGroup id="workspace-columns" orientation="horizontal" {...columns}>
          <ResizablePanel
            id="pane-sidebar"
            className="pane"
            panelRef={panes.sidebar.ref}
            onResize={panes.sidebar.onResize}
            defaultSize={380}
            minSize={280}
            maxSize="50%"
            collapsible
            groupResizeBehavior="preserve-pixel-size"
            style={{ overflow: "hidden" }}
          >
            {sidebar}
          </ResizablePanel>
          <ResizableHandle className="workspace-handle" />
          <ResizablePanel id="pane-map" className="pane" style={{ overflow: "hidden" }}>
            {map}
          </ResizablePanel>
        </ResizablePanelGroup>
      </ResizablePanel>
      <ResizableHandle className="workspace-handle" />
      <ResizablePanel
        id="pane-timeline"
        className="pane"
        panelRef={panes.timeline.ref}
        onResize={panes.timeline.onResize}
        defaultSize={200}
        minSize={168}
        maxSize="60%"
        collapsible
        groupResizeBehavior="preserve-pixel-size"
      >
        {timeline}
      </ResizablePanel>
    </ResizablePanelGroup>
  );
}

/** Top-bar buttons that show and hide the side panel and the timeline. */
export function PaneToggles({ panes }: { panes: Panes }) {
  if (!panes.wide) return null;
  const { sidebar, timeline } = panes;
  return (
    <div className="pane-toggles">
      <IconButton label={sidebar.open ? "Hide side panel" : "Show side panel"} onClick={() => sidebar.toggle()}>
        {sidebar.open ? <PanelLeftClose /> : <PanelLeftOpen />}
      </IconButton>
      <IconButton label={timeline.open ? "Hide timeline" : "Show timeline"} onClick={() => timeline.toggle()}>
        {timeline.open ? <PanelBottomClose /> : <PanelBottomOpen />}
      </IconButton>
    </div>
  );
}

/** The ✕ in a pane's own header. */
export function CloseButton({ label, onClick }: { label: string; onClick(): void }) {
  return (
    <IconButton label={label} onClick={onClick} size="icon-xs">
      <X />
    </IconButton>
  );
}

function IconButton({
  label,
  onClick,
  size = "icon-sm",
  children,
}: {
  label: string;
  onClick(): void;
  size?: "icon-sm" | "icon-xs";
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size={size} aria-label={label} onClick={onClick}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia?.(query).matches ?? true);
  useEffect(() => {
    const list = window.matchMedia?.(query);
    if (!list) return;
    const update = () => setMatches(list.matches);
    update();
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, [query]);
  return matches;
}
