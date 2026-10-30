#!/usr/bin/env bash
set -Eeuo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${repository_root}" <<'PY'
import json
import re
import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])


def read_match(path: str, pattern: str) -> str:
    match = re.search(pattern, (root / path).read_text(encoding="utf-8"), re.M)
    if not match:
        raise SystemExit(f"Could not read the version from {path}.")
    return match.group(1)


def read_json(path: str) -> dict:
    return json.loads((root / path).read_text(encoding="utf-8"))


lock = read_json("desktop/package-lock.json")
cargo_lock = tomllib.loads((root / "desktop/src-tauri/Cargo.lock").read_text(encoding="utf-8"))
versions = {
    "backend __version__": read_match("backend/src/eyespysc/__init__.py", r'^__version__\s*=\s*"([^"]+)"$'),
    "backend pyproject": tomllib.loads((root / "backend/pyproject.toml").read_text(encoding="utf-8"))["project"]["version"],
    "desktop package": read_json("desktop/package.json")["version"],
    "desktop package-lock": lock["version"],
    "desktop package-lock root": lock["packages"][""]["version"],
    "desktop appVersion.ts": read_match("desktop/src/appVersion.ts", r'^export const APP_VERSION\s*=\s*"([^"]+)";$'),
    "Tauri config": read_json("desktop/src-tauri/tauri.conf.json")["version"],
    "Cargo package": tomllib.loads((root / "desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8"))["package"]["version"],
    "Cargo.lock package": next(
        package["version"] for package in cargo_lock["package"] if package["name"] == "eyespysc-desktop"
    ),
}
if len(set(versions.values())) != 1:
    raise SystemExit("Release version metadata disagree: " + "; ".join(f"{key}={value}" for key, value in versions.items()))
print(f"release version consistency: ok ({next(iter(versions.values()))})")
PY
