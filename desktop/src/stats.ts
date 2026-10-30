// Pure helpers for the results panel. No imports, so `node --test` can load this
// file directly (Node strips the type annotations).

/** One row of summary.csv, as the CLI reports it with --json-progress. */
export type ImageSummary = {
  sperm_count: number;
  single_instances: number;
  overlap_clusters: number;
  heads_in_overlap_clusters: number;
  headless_tail_segments: number;
};

export type BatchStats = {
  images: number;
  total: number;
  mean: number;
  median: number;
  min: number;
  max: number;
};

export function batchStats(counts: number[]): BatchStats | null {
  if (counts.length === 0) return null;
  const sorted = [...counts].sort((a, b) => a - b);
  const n = sorted.length;
  const total = sorted.reduce((sum, value) => sum + value, 0);
  const middle = Math.floor(n / 2);
  const median = n % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  return { images: n, total, mean: total / n, median, min: sorted[0], max: sorted[n - 1] };
}

/** Whole numbers stay whole; everything else gets one decimal. */
export function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

/** "+2.4 vs. the mean of 15.6" style comparison for one image. */
export function compareToMean(count: number, mean: number): string {
  const difference = count - mean;
  const sign = difference >= 0 ? "+" : "−";
  return `${sign}${Math.abs(difference).toFixed(1)} vs. the mean of ${mean.toFixed(1)}`;
}

/** Local time as "2026-10-30 14.52.07", safe in folder names. */
export function folderTimestamp(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}.${pad(date.getMinutes())}.${pad(date.getSeconds())}`
  );
}

/** Last path component, ignoring a trailing slash. */
export function baseName(path: string): string {
  const parts = path.replace(/\/+$/, "").split("/");
  return parts[parts.length - 1] || path;
}

/** Parent folder of a path ("/" for top-level entries). */
export function parentPath(path: string): string {
  const trimmed = path.replace(/\/+$/, "");
  const index = trimmed.lastIndexOf("/");
  return index > 0 ? trimmed.slice(0, index) : "/";
}
