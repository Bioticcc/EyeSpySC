# EyeSpySC agent guide

## GitHub push and releases

- Name every release commit, annotated tag message, and GitHub release title
  `EyeSpySC v<version>: <short title>`, for example
  `EyeSpySC v0.1.0-rc.1: CLI-only release pipeline`. Tags are `v<version>`.
- Do not create a release tag until the exact intended commit has passed CI.
- A failed tag stays tied to its commit. Never reuse, move, or delete it; fix
  the problem and cut the next rc.
- Release readiness means the Debian package checks, the packaged smoke test,
  the build-revision match, and the single-ZIP contract all pass.
- Agents do not push tags or publish releases unless the user explicitly asks
  for that specific release.
- Change versions only with `./scripts/update-release-version.sh vX.Y.Z`.

Shared workspace rules (no GitHub attribution, lab-data handling, release
standard) are in `/home/kyle/Desktop/Adam/CLAUDE.md`. Read it if your tool did
not load it automatically.

## What this is

EyeSpySC counts sperm in low-contrast grayscale **20x phase-contrast** images.
It uses deterministic image processing only, with no model training. It came
out of the SCP project as `ColorMask-SpermCount-CellCount` and moved here on
2026-10-30. `README.md` documents the pipeline, outputs, limitations, and
validation status. Read it before changing behavior.

- Repo: `github.com/Bioticcc/EyeSpySC` (**private**). License: MIT, Yan Lab.
- `backend/src/eyespysc/sperm_count.py`: the whole pipeline and the
  `eyespysc` CLI (`main`).
- `backend/src/eyespysc/scp_helpers.py`: 4 functions copied unchanged from SCP
  (the header records the source commit). Do not edit them without recording
  the change. mypy strict is relaxed for this module only, to keep it verbatim.
- `backend/tests/test_sperm_count.py`: synthetic-image tests (no lab data).
- `scripts/check.sh`: the single quality gate, run locally and by CI.

## Setup and checks

```bash
make backend-install   # backend/.venv, Python 3.11
./scripts/check.sh
```

Regression baseline: the full test-image batch below must give a `summary.csv`
identical to `outputs/runFull/summary.csv` (100 images) unless the change is
meant to alter counts.

```bash
backend/.venv/bin/eyespysc --input inputsTest --output-root <scratch dir> \
  --minimal --magnification-from-filename
```

## Invariants

- **Pinned dependencies** (`backend/pyproject.toml`): numpy 2.2.6,
  opencv-python-headless 4.13.0.92, Pillow 12.2.0. Use **plain** OpenCV, never
  contrib. SCP's `skeletonize_binary` would switch to `cv2.ximgproc.thinning`
  under contrib, so the pipeline calls `zhang_suen_thinning` directly through
  `skeletonize()`. A test enforces this.
- Every pixel setting is tuned for 20x. Other magnifications are experimental.
- `--overwrite` deletes the output root. Use scratch or `outputs/` paths only.

## Data

`inputsTest/`, `outputs/`, and `validation/` are lab data and are git-ignored.
They stay local. Never commit images, CSVs, or ZIPs, and never modify the
input images.

## Status (2026-10-30)

- **Algorithm tuning is blocked:** we are waiting for the supervisor's expert
  sperm counts. Do not tune thresholds from the provisional (non-expert)
  counts. See README "Validation status and open counting rules".
- **Rerun the ZhengTest after re-tuning.** Once the expert counts arrive and
  the algorithm is updated, run `scripts/zheng-test.sh` again (numpy
  Zhang–Suen vs OpenCV-contrib thinning on the 12 review images). On
  2026-10-30 counts were identical and one head moved; we kept the numpy
  version. See `docs/Dev_Diary.md`.
- **Current work is release prep.** Follow
  `/home/kyle/Desktop/Adam/SOFTWARE_RELEASE_STANDARD.md`, **Appendix A**.
  Done: package layout; `check.sh` and CI (green on `a74a5d3`); PyInstaller
  sidecar, smoke test, CLI-only `.deb`, release ZIP, and
  `release-linux.yml` (verified locally). Next: a `workflow_dispatch` dry run
  of the release workflow, then `v0.1.0-rc.1` (only when the user asks), then
  the Tauri GUI. When `desktop/` is added, extend
  `check-version-consistency.sh` and `update-release-version.sh` to the
  desktop manifests, and keep the installed CLI command `/usr/bin/eyespysc`.
  Missus Tom (`/home/kyle/Desktop/Adam/MissusTom/`) is the reference
  implementation.

## Reference code (read-only)

The SCP research project is at
`/home/kyle/Desktop/Adam/Sperm_Morphology_Recognition/Algorithmic_Pixel_Mask_For_Tails/`
(`algorithmic_tail_mask.py` and the overlap-resolution modules). Read it for
algorithm ideas, but never modify it from EyeSpySC work, and never import from
it: copy code in with provenance instead.
