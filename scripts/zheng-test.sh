#!/usr/bin/env bash
set -Eeuo pipefail

# ZhengTest: run the pipeline twice on the same images, once with the shipped
# numpy Zhang-Suen thinning and once with OpenCV-contrib's
# cv2.ximgproc.thinning, then compare. See docs/Dev_Diary.md (2026-10-30).
#
# Usage: scripts/zheng-test.sh [INPUT] [OUTPUT]
# Defaults: outputs/Kyle_review_bundle/original_files outputs/runZhengTest
# OUTPUT is replaced. The contrib environment is cached in backend/build/.

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
input="${1:-${repository_root}/outputs/Kyle_review_bundle/original_files}"
output="${2:-${repository_root}/outputs/runZhengTest}"
dev_python="${repository_root}/backend/.venv/bin/python"
contrib_venv="${repository_root}/backend/build/zheng-test-venv"

if [[ ! -x "${dev_python}" ]]; then
  echo "Missing backend development environment (run: make backend-install)." >&2
  exit 1
fi
if [[ ! -e "${input}" ]]; then
  echo "Input does not exist: ${input}" >&2
  exit 2
fi

if [[ ! -x "${contrib_venv}/bin/python" ]]; then
  # Same pins as backend/pyproject.toml, with the contrib build of OpenCV.
  "${dev_python}" -m venv "${contrib_venv}"
  "${contrib_venv}/bin/pip" install --quiet numpy==2.2.6 Pillow==12.2.0 \
    opencv-contrib-python-headless==4.13.0.92
  "${contrib_venv}/bin/pip" install --quiet --no-deps -e "${repository_root}/backend"
fi

rm -rf "${output}"
mkdir -p "${output}"
"${dev_python}" -m eyespysc --input "${input}" --output-root "${output}/zhang_suen_numpy" \
  > "${output}/zhang_suen_numpy.log"
"${contrib_venv}/bin/python" -I "${repository_root}/scripts/zheng_test/run_contrib.py" \
  --input "${input}" --output-root "${output}/ximgproc_contrib" \
  > "${output}/ximgproc_contrib.log"
"${dev_python}" -I "${repository_root}/scripts/zheng_test/compare.py" "${output}" "${input}"
