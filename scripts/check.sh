#!/usr/bin/env bash
set -Eeuo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
project_root=$(cd "${script_dir}/.." && pwd)
venv_bin="${project_root}/backend/.venv/bin"

if [[ ! -x "${venv_bin}/pytest" ]]; then
  echo "Missing backend development environment (run: make backend-install)." >&2
  exit 1
fi

cd "${project_root}/backend"
"${project_root}/scripts/check-version-consistency.sh"
"${venv_bin}/ruff" check .
"${venv_bin}/ruff" format --check .
"${venv_bin}/mypy" src
"${venv_bin}/pytest"

for script in "${project_root}"/scripts/*.sh; do
  bash -n "${script}"
done
