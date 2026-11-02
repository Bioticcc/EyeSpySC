#!/usr/bin/env bash
set -Eeuo pipefail

# Run the frozen eyespysc CLI from a temporary state directory: check its
# version and build revision, then count a synthetic image (one sperm) made by
# the test-suite generators.

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <packaged-cli> [expected-build-revision]" >&2
  exit 2
fi

cli=$1
expected_revision=${2:-}
repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dev_python="${repository_root}/backend/.venv/bin/python"

if [[ ! -x "${cli}" ]]; then
  echo "Packaged CLI is not executable: ${cli}" >&2
  exit 2
fi
cli="$(cd "$(dirname "${cli}")" && pwd -P)/$(basename "${cli}")"

temporary_root=$(mktemp -d "${TMPDIR:-/tmp}/eyespysc-cli-smoke.XXXXXX")
trap 'rm -rf "${temporary_root}"' EXIT INT TERM
mkdir -p "${temporary_root}/home" "${temporary_root}/in"

expected_version=$(
  "${dev_python}" -c 'import eyespysc; print(eyespysc.__version__)'
)
version_output=$(cd "${temporary_root}" && HOME="${temporary_root}/home" "${cli}" --version)
# Without an expected revision, accept any build suffix.
expected_output="eyespysc ${expected_version}"
if [[ -n "${expected_revision}" ]]; then
  version_ok=$([[ "${version_output}" == "${expected_output} (build ${expected_revision})" ]] && echo 1 || echo 0)
else
  version_ok=$([[ "${version_output}" == "${expected_output}"* ]] && echo 1 || echo 0)
fi
if [[ "${version_ok}" != 1 ]]; then
  echo "Packaged CLI reported '${version_output}', expected '${expected_output}' (build ${expected_revision:-any})." >&2
  exit 1
fi

(
  cd "${repository_root}/backend"
  "${dev_python}" - "${temporary_root}/in/one_sperm.png" <<'PY'
import sys

import cv2

from tests.test_sperm_count import blank, draw_sperm, finish

img, rng = blank(13)
draw_sperm(img, (150, 200), 20)
cv2.imwrite(sys.argv[1], finish(img, rng))
PY
)

(
  cd "${temporary_root}"
  HOME="${temporary_root}/home" "${cli}" --input in --output-root out > run.log
)
python3 - "${temporary_root}/out" <<'PY'
import csv
import sys
from pathlib import Path

out = Path(sys.argv[1])
with (out / "summary.csv").open(newline="") as handle:
    rows = list(csv.DictReader(handle))
counts = [row["total_sperm"] for row in rows]
if counts != ["1"]:
    raise SystemExit(f"Packaged CLI counted {counts} on the one-sperm image, expected ['1'].")
if not (out / "batch_stats.csv").is_file():
    raise SystemExit("Packaged CLI did not write batch_stats.csv.")
for name in ("original.png", "overlay.png", "candidate_pixels.png", "instances.json"):
    if not (out / "one_sperm" / name).is_file():
        raise SystemExit(f"Packaged CLI did not write {name}.")
PY

# The desktop app drives the CLI with --preview-only and --json-progress.
(
  cd "${temporary_root}"
  HOME="${temporary_root}/home" "${cli}" --input in --output-root previews \
    --preview-only --json-progress > previews.jsonl
)
python3 - "${temporary_root}/previews.jsonl" <<'PY'
import json
import sys
from pathlib import Path

events = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
if [event["event"] for event in events] != ["start", "image", "done"]:
    raise SystemExit(f"Packaged CLI preview events were {events}.")
if not Path(events[1]["preview"]).is_file():
    raise SystemExit("Packaged CLI did not write the preview it reported.")
PY
echo "packaged CLI smoke test: ok (${version_output})"
