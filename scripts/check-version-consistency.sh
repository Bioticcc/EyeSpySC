#!/usr/bin/env bash
set -Eeuo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Desktop manifests (package.json, appVersion.ts, Cargo.toml, tauri.conf.json)
# join this check when the Tauri GUI is added.
python3 - "${repository_root}" <<'PY'
import re
import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])
backend_init = (root / "backend/src/eyespysc/__init__.py").read_text(encoding="utf-8")
match = re.search(r'^__version__\s*=\s*"([^"]+)"$', backend_init, re.M)
if not match:
    raise SystemExit("Could not read backend __version__.")
pyproject = tomllib.loads((root / "backend/pyproject.toml").read_text(encoding="utf-8"))
versions = {
    "backend __version__": match.group(1),
    "backend pyproject": pyproject["project"]["version"],
}
if len(set(versions.values())) != 1:
    raise SystemExit("Release version metadata disagree: " + "; ".join(f"{key}={value}" for key, value in versions.items()))
print(f"release version consistency: ok ({next(iter(versions.values()))})")
PY
