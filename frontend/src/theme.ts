// Colors that canvas and SVG code needs as values. The CSS custom properties in styles.css
// hold the same values for everything else. Violence and signals are categorical slots 2
// and 1 of the dataviz reference palette (dark steps), checked for colorblind separation
// against the panel surface.
export const COLORS = {
  violence: "#d95926",
  signal: "#3987e5",
  neutral: "#8a8781",
  deaths: "#c3c2b7",
  surface: "#14171b",
  ink: "#f0efec",
  muted: "#898781",
  grid: "#2a2e33",
  // Status "serious" from the reference palette, reserved for the surge alarm.
  alarm: "#ec835a",
} as const;
