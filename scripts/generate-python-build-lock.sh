#!/usr/bin/env bash
set -euo pipefail

# Generate the hash-checked Python release build lock in an isolated
# environment. Use Python 3.11, the release build interpreter: environment
# markers in the lock depend on it.
repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python="${EYESPYSC_LOCK_PYTHON:-python3.11}"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/eyespysc-pip-lock.XXXXXX")"
trap 'rm -rf "${work_dir}"' EXIT HUP INT TERM
"${python}" -m venv "${work_dir}/venv"
"${work_dir}/venv/bin/pip" install --quiet 'pip-tools==7.5.2'
(
  cd "${repository_root}/backend"
  "${work_dir}/venv/bin/pip-compile" --quiet --generate-hashes --strip-extras \
    --output-file requirements-build.lock requirements-build.in
)
