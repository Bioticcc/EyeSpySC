// rc.3 shipped @tauri-apps/api 2.2 against the tauri 2.11 crate. Their channel
// message formats differ, so the app received no progress events and the
// slideshow never loaded. Keep each JavaScript package on its crate's
// major.minor.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const root = new URL("../", import.meta.url);
const lock = JSON.parse(readFileSync(new URL("package-lock.json", root), "utf8"));
const cargoLock = readFileSync(new URL("src-tauri/Cargo.lock", root), "utf8");

function crateVersion(name: string): string {
  const match = cargoLock.match(new RegExp(`^name = "${name}"\\nversion = "([^"]+)"$`, "m"));
  assert.ok(match, `${name} is missing from Cargo.lock`);
  return match[1];
}

function npmVersion(name: string): string {
  const entry = lock.packages[`node_modules/${name}`];
  assert.ok(entry, `${name} is missing from package-lock.json`);
  return entry.version;
}

const majorMinor = (version: string) => version.split(".").slice(0, 2).join(".");

for (const [npmName, crateName] of [
  ["@tauri-apps/api", "tauri"],
  ["@tauri-apps/cli", "tauri"],
  ["@tauri-apps/plugin-dialog", "tauri-plugin-dialog"],
]) {
  test(`${npmName} matches the ${crateName} crate`, () => {
    assert.equal(majorMinor(npmVersion(npmName)), majorMinor(crateVersion(crateName)));
  });
}
