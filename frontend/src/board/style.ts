// Board colours, the same as the gods-eye-view fork's (src/scenes/dataPacks/geometry.js),
// so a board looks alike on the map and on the globe. Keys are the API's `style` values.
export const BOARD_STYLE_COLORS: Record<string, string> = {
  article: "#ffffff",
  place: "#ffd166",
  actor: "#c77dff",
  claim: "#f4a261",
  "event-violent": "#ef476f",
  "event-signal": "#f8961e",
  "history-violent": "#b5838d",
  "history-signal": "#a68a64",
  flight: "#4cc9f0",
  fire: "#ff5400",
  vessel: "#4361ee",
  note: "#adb5bd",
};

export const KIND_LABELS: Record<string, string> = {
  article: "Article",
  place: "Places",
  actor: "Groups and forces",
  claim: "Reported by the article",
  event: "Events",
  flight: "Flights",
  fire: "Fires",
  vessel: "Ships",
  note: "Notes",
};

export const RULE_LABELS: Record<string, string> = {
  mentions: "Named in article",
  reports: "Article reports",
  coded_from: "Coded from article",
  near: "Nearby",
  history: "Earlier here",
  same_actor: "Same actor",
  same_incident: "Same incident",
  co_reported: "Same report",
  user: "Your link",
};

export function nodeStyle(node: { kind: string; attributes: Record<string, unknown> }): string {
  if (node.kind !== "event") return node.kind;
  const prefix = node.attributes.history ? "history" : "event";
  return `${prefix}-${node.attributes.violent ? "violent" : "signal"}`;
}

export function nodeColor(node: { kind: string; attributes: Record<string, unknown> }): string {
  return BOARD_STYLE_COLORS[nodeStyle(node)] ?? BOARD_STYLE_COLORS.note!;
}
