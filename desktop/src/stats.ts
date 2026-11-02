// Pure helpers for the results panel. No imports, so `node --test` can load this
// file directly (Node strips the type annotations).

/** One row of summary.csv, as the CLI reports it with --json-progress. */
export type ImageSummary = {
  total_sperm: number;
  intact: number;
  tailless: number;
  headless: number;
  total_heads: number;
  total_tails: number;
  barely_visible: number;
  overlap_clusters: number;
};

type CountKey = "total_sperm" | "intact" | "tailless" | "headless" | "total_heads" | "total_tails" | "barely_visible";

export const COUNT_ROWS: { key: CountKey; label: string }[] = [
  { key: "total_sperm", label: "Total sperm" },
  { key: "intact", label: "Intact" },
  { key: "tailless", label: "Tail-less" },
  { key: "headless", label: "Head-less" },
  { key: "total_heads", label: "Total heads" },
  { key: "total_tails", label: "Total tails" },
  { key: "barely_visible", label: "Barely visible" },
];

/** The overlay's colors. A test keeps them equal to the ones in sperm_count.py. */
export const COLOR_KEY: { label: string; constant: string; rgb: [number, number, number]; ring?: boolean }[] = [
  { label: "Intact", constant: "INTACT_COLOR", rgb: [0, 220, 90] },
  { label: "Tail-less", constant: "TAILLESS_COLOR", rgb: [230, 70, 230], ring: true },
  { label: "Head-less", constant: "HEADLESS_COLOR", rgb: [0, 170, 255] },
  { label: "Barely visible", constant: "BARELY_VISIBLE_COLOR", rgb: [240, 220, 60] },
  { label: "Overlap cluster", constant: "CLUSTER_COLOR", rgb: [255, 140, 0] },
  { label: "Head on a tail", constant: "HEAD_COLOR", rgb: [255, 40, 40], ring: true },
];

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

/** Batch stats for every count, in display order. */
export function countTable(summaries: ImageSummary[]) {
  return COUNT_ROWS.flatMap(({ key, label }) => {
    const stats = batchStats(summaries.map((summary) => summary[key]));
    return stats ? [{ key, label, stats }] : [];
  });
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
