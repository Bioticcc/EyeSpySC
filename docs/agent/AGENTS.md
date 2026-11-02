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
- `desktop/`: the Tauri 2 + React GUI. It runs the `eyespysc` CLI once per
  job with `--json-progress` (and `--preview-only` for the slideshow) and
  never counts by itself. `src-tauri/src/lib.rs` holds the native commands;
  `src/App.tsx` the one workspace screen. `src/houseStyle.css` is a verbatim
  copy from Missus Tom; edit `src/styles.css` instead.
- `scripts/check.sh`: the single quality gate, run locally and by CI.

## Setup and checks

```bash
make backend-install    # backend/.venv, Python 3.11
make frontend-install   # desktop/node_modules
./scripts/check.sh
make desktop-dev        # run the GUI from source
```

Regression baseline: the full test-image batch below must give a `summary.csv`
identical to `outputs/runFull_2026-11-02/summary.csv` (100 images) unless the
change is meant to alter counts.

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
- **Tauri versions must match.** `@tauri-apps/api`, `@tauri-apps/cli` and
  `@tauri-apps/plugin-dialog` stay on the same major.minor as the pinned
  `tauri` and `tauri-plugin-dialog` crates (a test enforces it). rc.3 broke on
  a mismatch; see `docs/Dev_Diary.md`.
- The GUI never passes `--overwrite`: every run writes a new time-stamped
  folder. The installed commands are `/usr/bin/eyespysc` (CLI, unchanged
  since rc.1) and `/usr/bin/eyespysc-desktop` (GUI).

## Data

`inputsTest/`, `outputs/`, and `validation/` are lab data and are git-ignored.
They stay local. Never commit images, CSVs, or ZIPs, and never modify the
input images.

- **One exception, approved by the user on 2026-10-30:**
  `validation/provisional_counts_2026-10-28.csv` (the user's own non-expert
  counts for the 12 review images) is committed. Commit expert counts only
  if the user approves that too.
- **No testing environment.** The user decided EyeSpySC skips the standard's
  `EyeSpySC_Testing-Environment/` (section 11 and Appendix A). Lab data stays
  in this folder, git-ignored.

## Status (2026-11-02)

- **Counting rule (supervisor, 2026-11-02).** Four categories: intact,
  tail-less, head-less, barely visible. Total sperm = intact + the larger of
  tail-less and head-less, per image. Barely visible tails are reported
  separately. See README "Validation status and open counting rules".
- **Reference counts:** `outputs/Kyle_review_bundle/count_sheet_supervisor_updated.csv`
  (git-ignored). `total_count_with_tailless` counts every head, tail, and intact
  sperm found, before the rule, so compare it with intact + tail-less + head-less.
  With `total_count` it gives lower and upper bounds for testing. Use this sheet
  for tuning, not the provisional (non-expert) counts. Thresholds have not been
  tuned against it yet, and these 12 images should not be the only check: tuning
  needs a held-out set that includes cauda.
- **Rerun the ZhengTest after re-tuning.** Once the reference counts arrive and
  the algorithm is updated, run `scripts/zheng-test.sh` again (numpy
  Zhang–Suen vs OpenCV-contrib thinning on the 12 review images). On
  2026-10-30 counts were identical and one head moved; we kept the numpy
  version. See `docs/Dev_Diary.md`.
- **Release prep.** Following
  `/home/kyle/Desktop/Adam/SOFTWARE_RELEASE_STANDARD.md`, **Appendix A**.
  CLI-only releases `v0.1.0-rc.1` and `rc.2` are published by CI. `rc.2`
  passed the clean-machine install check on a fresh Ubuntu VM and WSL2
  Ubuntu (2026-10-30). `v0.1.0-rc.3` adds the GUI. The user decided
  (2026-10-30) that the GUI ships within 0.1.0, and that 0.1.0 is published
  after they test rc.3 by hand.
- **GUI: implemented in rc.3, designed with the user.** User requirements
  (2026-10-30):
  1. Missus Tom house style (standard section 3) with the logo in the sidebar
     and on About (principle 7).
  2. **Minimal clutter.** The user gives one image or a folder, and the app
     reports the sperm count and statistics. That is the whole job.
  3. **20x is fixed.** Show "20x objective" as read-only text. There is no
     magnification control.
  4. **Results are shown in the app and also saved to files** (the CLI's
     outputs). One workspace screen does the whole job:
     - Choosing an image or a folder opens the originals as a slideshow
       (prev/next, arrow keys, thumbnails).
     - Count sperm switches each image to its overlay as it finishes.
     - A side panel then shows the stats for the current image and for the
       whole batch (total, mean per image, ...).

     More stats will be added later.
  5. Non-sperm cell counting comes later, after the sperm counts are good.

  Approved mock-up: https://claude.ai/artifact/7iQUUDxCBjqDtFWzQ81bnD. Ask
  before adding screens or controls beyond these. Missus Tom
  (`/home/kyle/Desktop/Adam/MissusTom/`) is the reference implementation.

## Reference code (read-only)

The SCP research project is at
`/home/kyle/Desktop/Adam/Sperm_Morphology_Recognition/Algorithmic_Pixel_Mask_For_Tails/`
(`algorithmic_tail_mask.py` and the overlap-resolution modules). Read it for
algorithm ideas, but never modify it from EyeSpySC work, and never import from
it: copy code in with provenance instead.
