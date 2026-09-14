export type IconName =
  | "box"
  | "grid"
  | "search"
  | "chevron-left"
  | "chevron-right"
  | "close"
  | "sparkles"
  | "leaf"
  | "arrow"
  | "user"
  | "refresh"
  | "check";
const paths: Record<IconName, string> = {
  box: "M3 8h18v12H3z M2 4h20v4H2z M9 12h6",
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  search: "M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  "chevron-left": "M15 5l-7 7 7 7",
  "chevron-right": "M9 5l7 7-7 7",
  close: "M6 6l12 12 M18 6L6 18",
  sparkles:
    "M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z M21 2v4 M19 4h4",
  leaf: "M20 3C8 1 2 7 4 15c2 7 15 6 16-12z M4 21L15 9",
  arrow: "M4 12h16 M14 6l6 6-6 6",
  user: "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M4 21v-2a8 8 0 0 1 16 0v2",
  refresh: "M20 7a9 9 0 1 0 1 8 M20 2v6h-6",
  check: "M4 12l5 5L20 6",
};
export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
export function Ball({ className = "" }: { className?: string }) {
  return (
    <span className={`pokeball ${className}`} aria-hidden="true">
      <i />
    </span>
  );
}
