export function Logo({ size = 22 }: { size?: number }) {
  // One continuous stroke forming a frame + play glyph; accent dot = the "line" origin.
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      style={{ display: "block", overflow: "visible" }}
    >
      <rect x="2.5" y="2.5" width="19" height="19" rx="5.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M9.5 8.2 L16 12 L9.5 15.8 Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <circle cx="20.5" cy="3.5" r="2.1" fill="var(--accent, #C4F82A)" />
    </svg>
  );
}
