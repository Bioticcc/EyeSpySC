#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 || ! "$1" =~ ^v([0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z][0-9A-Za-z.-]*)?)$ ]]; then
  echo "Usage: $0 vMAJOR.MINOR.PATCH[-PRERELEASE]" >&2
  exit 2
fi

release_tag="$1"
release_version="${release_tag#v}"
repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${repository_root}" "${release_version}" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
version = sys.argv[2]


def replace_once(path: Path, pattern: str, replacement: str) -> None:
    content = path.read_text(encoding="utf-8")
    updated, replacements = re.subn(pattern, replacement, content, count=1, flags=re.M)
    if replacements != 1:
        raise SystemExit(f"Could not update the release version in {path.relative_to(root)}.")
    path.write_text(updated, encoding="utf-8")


replace_once(
    root / "backend/pyproject.toml",
    r'^(version\s*=\s*)"[^"]+"$',
    rf'\g<1>"{version}"',
)
replace_once(
    root / "backend/src/eyespysc/__init__.py",
    r'^(__version__\s*=\s*)"[^"]+"$',
    rf'\g<1>"{version}"',
)
PY

"${repository_root}/scripts/check-version-consistency.sh"
printf 'Updated release metadata for %s.\n' "${release_tag}"
