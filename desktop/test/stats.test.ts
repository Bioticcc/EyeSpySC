import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  baseName,
  batchStats,
  COLOR_KEY,
  compareToMean,
  countTable,
  folderTimestamp,
  formatNumber,
  parentPath,
} from "../src/stats.ts";

test("batch stats for odd and even counts", () => {
  assert.equal(batchStats([]), null);
  assert.deepEqual(batchStats([15, 20, 9]), {
    images: 3,
    total: 44,
    mean: 44 / 3,
    median: 15,
    min: 9,
    max: 20,
  });
  assert.equal(batchStats([4, 1, 3, 2])?.median, 2.5);
});

test("count table covers every count, in order", () => {
  assert.deepEqual(countTable([]), []);
  const one = { total_sperm: 5, intact: 2, tailless: 1, headless: 2, total_heads: 3, total_tails: 4, barely_visible: 1, overlap_clusters: 0 };
  const two = { total_sperm: 9, intact: 4, tailless: 3, headless: 2, total_heads: 7, total_tails: 6, barely_visible: 3, overlap_clusters: 1 };
  const table = countTable([one, two]);
  assert.deepEqual(
    table.map((row) => row.label),
    ["Total sperm", "Intact", "Tail-less", "Head-less", "Total heads", "Total tails", "Barely visible"],
  );
  assert.equal(table[0].stats.total, 14);
  assert.equal(table[5].stats.mean, 5);
  assert.equal(table[6].stats.total, 4);
});

test("the color key matches the overlay colors", () => {
  const source = readFileSync(new URL("../../backend/src/eyespysc/sperm_count.py", import.meta.url), "utf8");
  for (const { constant, rgb } of COLOR_KEY) {
    const match = source.match(new RegExp(`^${constant} = \\((\\d+), (\\d+), (\\d+)\\)$`, "m"));
    assert.ok(match, `${constant} is missing from sperm_count.py`);
    assert.deepEqual(match.slice(1).map(Number), rgb, constant);
  }
});

test("number formatting and mean comparison", () => {
  assert.equal(formatNumber(15), "15");
  assert.equal(formatNumber(14.666), "14.7");
  assert.equal(compareToMean(17, 15.6), "+1.4 vs. the mean of 15.6");
  assert.equal(compareToMean(12, 15.6), "−3.6 vs. the mean of 15.6");
});

test("folder timestamp is local time and folder-safe", () => {
  assert.equal(folderTimestamp(new Date(2026, 9, 30, 14, 5, 7)), "2026-10-30 14.05.07");
});

test("path helpers", () => {
  assert.equal(baseName("/data/caput/"), "caput");
  assert.equal(baseName("/data/caput/a.tif"), "a.tif");
  assert.equal(parentPath("/data/caput/a.tif"), "/data/caput");
  assert.equal(parentPath("/a.tif"), "/");
});
