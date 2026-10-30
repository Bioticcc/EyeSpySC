#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend_root="${repository_root}/backend"
target="${1:-x86_64-unknown-linux-gnu}"
sidecar_python="${EYESPYSC_SIDECAR_PYTHON:-${backend_root}/.venv/bin/python}"

if [[ "${sidecar_python}" != /* ]]; then
  sidecar_python="$(pwd -P)/${sidecar_python}"
fi

case "${target}" in
  x86_64-unknown-linux-gnu)
    ;;
  *)
    echo "Only the Linux target x86_64-unknown-linux-gnu is supported." >&2
    exit 2
    ;;
esac

if [[ ! -x "${sidecar_python}" ]]; then
  echo "Sidecar build requires an executable backend Python interpreter at ${sidecar_python}." >&2
  echo "Create backend/.venv and install backend[dev,packaging], or set EYESPYSC_SIDECAR_PYTHON." >&2
  exit 1
fi

if ! "${sidecar_python}" -c "import PyInstaller"; then
  echo "PyInstaller is not installed for ${sidecar_python}. Install backend[dev,packaging] there." >&2
  exit 1
fi
if "${sidecar_python}" -c "import cv2, sys; sys.exit(0 if hasattr(cv2, 'ximgproc') else 1)"; then
  echo "OpenCV-contrib is installed for ${sidecar_python}; release builds use plain OpenCV only." >&2
  exit 1
fi

resource_stage="${backend_root}/build/sidecar-resources"
rm -rf "${resource_stage}"
mkdir -p "${resource_stage}"
git -C "${repository_root}" rev-parse HEAD > "${resource_stage}/build_revision.txt"

export EYESPYSC_SIDECAR_TARGET="${target}"
export EYESPYSC_SIDECAR_RESOURCE_STAGE="${resource_stage}"

cd "${backend_root}"
"${sidecar_python}" -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "${backend_root}/dist/sidecars" \
  --workpath "${backend_root}/build/pyinstaller" \
  "${backend_root}/packaging/eyespysc_sidecars.spec"
