import assert from "node:assert/strict";
import { test } from "node:test";

import {
  baseName,
  batchStats,
  compareToMean,
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
