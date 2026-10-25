// The Atlas globe, matching public/favicon.svg and the loading screen in index.html.
export function BrandMark({ size = 20 }: { size?: number }) {
  return (
    <svg className="brand-mark" width={size} height={size} viewBox="0 0 100 100" aria-hidden>
      <circle cx="50" cy="50" r="40" fill="none" stroke="var(--accent)" strokeWidth="8" />
      <ellipse cx="50" cy="50" rx="18" ry="40" fill="none" stroke="var(--accent)" strokeWidth="5" opacity=".6" />
      <line x1="10" y1="50" x2="90" y2="50" stroke="var(--accent)" strokeWidth="5" opacity=".6" />
      <circle cx="66" cy="34" r="8" fill="var(--ink)" />
    </svg>
  );
}
