# EyeSpySC

EyeSpySC (formerly ColorMask-SpermCount-CellCount) is a smaller, practical
offshoot of **Sperm Color Pixels (SCP)**
([SCP-SpermColorPixels](https://github.com/Bioticcc/SCP-SpermColorPixels),
`Algorithmic_Pixel_Mask_For_Tails/algorithmic_tail_mask.py`). This project highlights and counts sperm in
**low-contrast grayscale phase-contrast images** of the kind the lab already
produces (for example, `EXAMPLE_testis_0007_TRANS.tif`). It needs no change to
the current imaging setup.

Like SCP, it is fully deterministic image processing. There is no model
training and no learned image recognition.

**Status: prerelease.** Counts are provisional. They have not yet been
validated against expert counts (see
[Validation status](#validation-status-and-open-counting-rules)).

## Install

Releases are on the GitHub releases page as one ZIP per version,
`EyeSpySC_ver<version>_Linux-x86_64_Ubuntu-Debian.zip`. It holds the `.deb`,
`SHA256SUMS`, and `installation.md`. Supported: Ubuntu 22.04+ and Debian 12+
on x86_64, and Windows 10/11 through WSL2 Ubuntu. No Python is needed.

```bash
unzip EyeSpySC_ver<version>_Linux-x86_64_Ubuntu-Debian.zip
sha256sum --check SHA256SUMS
sudo apt install ./eyespysc_<version>_linux-x86_64.deb
```

The package installs two things:

- the **EyeSpySC desktop app**: open "EyeSpySC" from the applications menu, or
  run `eyespysc-desktop`;
- the **`eyespysc` command**, which takes the options described under
  [Run](#run).

Uninstall with `sudo apt remove eyespysc`. On WSL, the app opens through
WSLg. Keep images under the Linux filesystem (`~/...`): it is much faster than
`/mnt/c/...`.

## Desktop app

1. **Choose folder…** or **Choose images…** (TIFF or PNG, 20x phase
   contrast). The images open as a slideshow. Move through them with
   Prev / Next, the arrow keys, or the thumbnails.
2. **Count sperm.** Each image switches to its overlay as soon as it is
   counted. The count shows on its thumbnail.
3. The side panel shows the current image's count (single sperm, sperm in
   overlap clusters, and headless tails, which are not counted), and the batch
   totals: total sperm, mean and median per image, and range.

Every run saves to a new folder, by default
`~/EyeSpySC results/<folder name> <date time>/` ("Change…" picks another
place). It contains `summary.csv` and, per image, `original.png`,
`overlay.png`, and `candidate_pixels.png` (the CLI's `--minimal` output).
Earlier results are never overwritten. The magnification is fixed at 20x.

The app runs the bundled `eyespysc` command for the work. Its counts are the
same as the command line's.

## Input requirements

| Requirement | Expected |
|---|---|
| Magnification | **20x objective for all inputs.** Every pixel setting is tuned for 20x |
| Imaging | Grayscale phase contrast (TRANS channel), as currently acquired by the lab |
| Format | 8-bit or 16-bit TIFF/PNG (16-bit is scaled to 8-bit); RGB is converted to gray |
| Frame size | About 2048×1536. Larger frames scale settings up |
| Density | **Reasonable density.** Sperm are mostly separable, and occasional crossing or touching tails are fine |

**Out of scope:**
- Other magnifications, such as the `*_40x_*` test images.
- Extremely crowded frames with hundreds of tangled sperm, such as
  `20231002 cauda_0035`.

Neither is expected in normal use.

**Busy but reasonable frames are in scope.** For example,
`20231215 cauda_0020` counts 52 and visually looks close to complete.

## How this differs from SCP

| | SCP (parent project) | This project |
|---|---|---|
| Input | High-contrast RGB Ward TIFFs, brown stain on a light background | 8-bit grayscale phase contrast (RGB inputs are converted to gray) |
| Sperm-pixel cue | Brown/olive HSV stain gate plus local darkness | Hessian ridge (line) filter plus local darkness |
| Overlap | The main open research problem (R1–R4 path search and assignment) | Assumed rare. If tails do connect, the whole mass is highlighted and its **heads** are counted |
| Main output | Per-sperm crops for morphology review | A **sperm count** per image, plus masks, crops, and an overlay |

The SCP overlap-resolution work (R-series experiments) is on hold. Nothing in
this folder depends on it or changes it.

## What was reused from SCP

- **Local-background darkness:** grayscale minus a heavily blurred background
  (`build_candidate_masks` in SCP). This is the part of SCP's pixel masking
  that still works without color.
- **SCP helpers, copied unchanged into `backend/src/eyespysc/scp_helpers.py`:**
  `skeletonize_binary` with its Zhang–Suen fallback, `prune_skeleton_endpoints`,
  and `remove_small_components`. The file header records the source commit.
  The pipeline calls Zhang–Suen directly, so an OpenCV-contrib install cannot
  switch it to `cv2.ximgproc.thinning`.
- **The longest-path idea** from SCP's `skeleton_longest_path`. It is
  reimplemented here so it returns ordered points, which makes arc length and
  straightness measurable.
- **Scale handling:** pixel thresholds only grow for frames larger than the
  reference size.

SCP's stain gate (`hue`/`sat` thresholds) cannot work on grayscale input, so it
was replaced rather than retuned.

## Pipeline (`backend/src/eyespysc/sperm_count.py`)

1. **Background flattening and noise estimate.** A large Gaussian background
   is subtracted. A robust (MAD) noise sigma is measured.
2. **Tail pixels.** A multi-scale Hessian ridge filter (σ = 1.5, 2.5 px)
   responds to thin dark lines. A hysteresis threshold keeps faint tail
   stretches only when they connect to strong ones. Thresholds are expressed
   as median + k·MAD of the ridge response, so they do not drift with sperm
   density or debris load. A small closing bridges 1–3 px gaps.
3. **Dark blobs.** Pixels at least 5 noise-sigmas darker than the background
   are candidate heads, midpieces, or debris.
4. **Sperm masses.** These are connected components of (ridge ∪ dark blob).
   A component is kept as sperm-bearing only when its longest skeleton path:
   - is at least 100 px long;
   - has at least 100 px of *thin* path (half-width ≤ 3.5 px);
   - is **locally** straight (median windowed chord/arc ≥ 0.9). Tails are
     locally straight even where they cross, while debris outlines curl at
     every scale.

   An earlier gate (the longest path must make up at least 40% of the
   skeleton) was removed. It rejected whole tangles of several sperm, and the
   local-straightness test already rejects debris on its own.
5. **Heads.** A morphological opening strips the midpiece and tail, leaving
   thick "cores". It runs twice:
   - with a 7 px opening, for normal heads;
   - with a 5 px opening, for slender side-on heads.

   Accepted heads from the two passes are merged. Two heads count as one when
   they share a dark blob or lie within 15 px of each other. In the thin pass a
   core is also rejected when any other skeleton segment of 15 px or more
   leaves it, because otherwise a dark midpiece segment can pass for a head.
   Nearby cores are grouped. The skeleton is split at true
   junctions (crossing number ≥ 3). A core is a head only when **exactly one
   tail-like segment terminates at it**:
   - debris that a tail passes *through* has two terminating segments, so it
     is rejected;
   - debris that only touches the *side* of a tail has none, so it is
     rejected;
   - a core with no tail attached is rejected.

   Inside a multi-head mass, a candidate whose neck (first 30 px of tail) is
   much fainter than the others is treated as debris on a tail end. Real
   midpieces are dark. This rule is applied after the two passes are merged.
6. **Classification and count.** Each component is classified:

   | Kind | Heads | Highlighted as | Counted |
   |---|---|---|---|
   | `single` | 1 | Green | 1 |
   | `overlap_cluster` | 2 or more | Orange (the whole connected mass) | Number of heads |
   | `headless_tail` | 0 | Blue | 0, reported separately |

   **Sperm count = total accepted heads.**

Every head candidate is written to `instances.json` with its measurements and
an accept/reject `reason`, so threshold tuning can be done from data.

## Setup

Requires Python 3.11+, and for the desktop app Node.js 22 and the Rust
toolchain pinned in `rust-toolchain.toml` (plus the Tauri Linux packages:
`libwebkit2gtk-4.1-dev`, `librsvg2-dev`, `libayatana-appindicator3-dev`). From
this folder:

```bash
make backend-install    # backend/.venv with the eyespysc package and dev tools
make frontend-install   # desktop/node_modules
make desktop-dev        # run the app from source (counts with backend/.venv)
```

The GUI follows the house style (`SOFTWARE_RELEASE_STANDARD.md` section 3).
`desktop/src/houseStyle.css` is copied verbatim from Missus Tom; EyeSpySC's own
rules are in `desktop/src/styles.css`.

`backend/pyproject.toml` pins the exact versions used for the validated counts
(numpy 2.2.6, opencv-python-headless 4.13.0.92, Pillow 12.2.0). Use plain
OpenCV, never contrib.

Test images (`inputsTest/`), outputs (`outputs/`), and validation counts are
lab data. They are git-ignored and never committed.

## Run

From this folder:

```bash
backend/.venv/bin/eyespysc --input inputsTest/EXAMPLE_testis_0007_TRANS.tif \
  --output-root outputs/run --overwrite
```

- `--input` (required) is an image file or a folder, searched recursively.
  Repeat it to count several files or folders together. Subfolders named
  `outputs` are skipped. Output folders mirror the input subfolders, because
  the same file name recurs across sessions. If two inputs would write to the
  same output folder, the command stops before counting.
- `--output-root` (required) is created for the results.
- `--minimal` writes only `original.png` (the input as an unannotated 8-bit
  PNG, for comparison), `overlay.png`, and `candidate_pixels.png` per image,
  plus the root `summary.csv`.
- `--magnification N` defaults to **20**, the lab standard. Leave it alone for
  normal use. Other values scale every length and area by N/20 and switch on
  an experimental relief-contrast mode from 40x up. Neither is validated, and
  both are kept only for experiments.
- `--magnification-from-filename` reads a `_<N>x_` token from file names (for
  example `caput_40x_0019`) and otherwise falls back to `--magnification`. It
  is only useful for test folders that mix in non-20x images.
- 16-bit PNG/TIFF inputs are scaled to 8 bits by dropping the low byte, which
  keeps them in the same brightness range as the 8-bit captures.

Full batch over the test set:

```bash
backend/.venv/bin/eyespysc --input inputsTest --output-root outputs/runFull \
  --minimal --magnification-from-filename --overwrite
```

- `--overwrite` deletes and recreates the output root. Without it, the command
  refuses to touch an existing output folder.
- `eyespysc --version` prints the version. `python -m eyespysc` also works.
- `--json-progress` prints one JSON object per line (`start`, one `image` per
  image with its summary row and output paths, `done`) instead of text. The
  desktop app reads this.
- `--preview-only` counts nothing. It writes an 8-bit `preview.png` (long side
  at most 1600 px) per image, for the app's slideshow.

## Outputs

`<output-root>/summary.csv` holds one row per image: sperm count, single and
overlap counts, headless tail segments, and noise and threshold values.

Each image also gets a folder, `<output-root>/<image-stem>/`, containing:

| File | Contents |
|---|---|
| `original.png` | The input as an 8-bit grayscale PNG, unannotated |
| `overlay.png` | Colored instances, numbered head markers, and the count banner |
| `sperm_mask.png` | Binary union of the accepted sperm masses |
| `instance_labels.png` | 16-bit instance id map (0 = background) |
| `candidate_pixels.png` | Raw ridge ∪ dark-blob mask before shape filtering (debug) |
| `instances.json` | Summary, plus per-instance geometry and head-candidate diagnostics |
| `crops/NNN_<kind>.png` | One padded crop per instance |

## Tests

```bash
./scripts/check.sh   # version consistency, ruff, mypy --strict, pytest,
                     # desktop lint, tests, typecheck, and build
```

CI runs the same script on every push, plus `cargo test` for the desktop shell.

## Packaging and releases

Releases are built only by GitHub Actions from an annotated tag; see
[docs/RELEASING.md](docs/RELEASING.md). The build:

1. installs hash-locked dependencies (`backend/requirements-build.lock`,
   regenerated with `scripts/generate-python-build-lock.sh`);
2. freezes the CLI with PyInstaller (`scripts/build-linux-sidecars.sh`);
3. smoke-tests the binary on a synthetic image (`scripts/smoke-packaged-cli.sh`);
4. builds the Tauri desktop app with the CLI as its sidecar
   (`npm run tauri:release`), producing one `.deb` with `/usr/bin/eyespysc`
   and `/usr/bin/eyespysc-desktop`;
5. checks the package contents and smoke-tests the packaged CLI again, then
   writes the release ZIP (`scripts/create-linux-release-zip.sh`).

Versions are changed only with `./scripts/update-release-version.sh vX.Y.Z`.

The tests use synthetic phase-contrast-like images. They cover:

- a single sperm and two separate sperm;
- crossing tails (one overlap cluster, two heads counted);
- debris and round cells (not counted);
- debris in the middle of a tail (not a second head);
- headless tails;
- pure noise;
- determinism;
- junction and endpoint helpers, local straightness, and ordered path
  measurement;
- output files, including RGB input, 16-bit input, and minimal mode;
- magnification scaling, file-name parsing, and the 40x preset;
- the command line, end to end (`--version`, batch run, overwrite refusal,
  JSON progress, preview-only, several inputs and output collisions);
- Zhang–Suen thinning even when OpenCV-contrib is present.

## Current results on the example image

`EXAMPLE_testis_0007_TRANS.tif` gives **12 sperm**: 12 single, 0 overlap
clusters, and 1 headless tail segment. These results were checked visually.

- Every counted sperm corresponds to a visible sperm, with the marker on its
  head.
- Debris clumps touching tails were rejected, and so was a crossing headless
  tail.
- Three sperm that run off the image edge were not counted.

## Known limitations

- **Sperm cut off by the image border** are missed when less than about
  100 px of tail is visible. One head on the bottom edge whose tail runs
  through another sperm is also suppressed by the faint-neck rule.
- **Debris on the far end of a tail** looks like a head-at-terminus. It is
  rejected only when the mass also contains a real head with a darker neck.
- **Headless tails that cross a headed sperm** are included in that sperm's
  mask. They are not counted, but the mask is larger than one sperm.
- **The thresholds were tuned on a single example image.** The local
  straightness margin is narrow: real tails scored 0.91–0.96 and the worst
  debris scored 0.89. Validate on more images before relying on the counts.
- **Overlap clusters are not yet validated against manual counts.** They pass
  the synthetic tests and look right on busy frames such as
  `20231215 cauda_0020`.
- **Non-20x images are out of scope.** At 40x, sperm look different, not just
  bigger: there is relief contrast, the head is an open, hollow hook, and the
  midpiece is a thick two-edged band. The experimental 40x preset misses most
  heads.
- **Heads lying on another sperm's tail** are seen as "tail passes through"
  and are not counted. This is the main remaining miss in the 20231215
  folder (for example the central tangle in `caput_0016`).
- **Extremely crowded frames** (for example `20231002 cauda_0035`, with
  hundreds of tangled sperm) are out of scope, and their counts are not
  meaningful. See [Input requirements](#input-requirements).
- **Some headless tails may have a curled head** that wasn't recognized (for
  example #5 in `20231215 cauda_0020`). This can make counts slightly low.

## Validation status and open counting rules

**Provisional (non-expert) counts** for 12 images, made by the project's
developer, are in `validation/provisional_counts_2026-10-28.csv` (the only
lab-data file committed to this repository), together with the algorithm's
count from the same date. On these images the algorithm undercounted every
time and never overcounted. It found 126 sperm against 202 counted by hand
(about 62%).

**No tuning has been done from these counts.** Expert reference counts come
first.

**Expert counts requested.** A blind bundle (original image files plus a count
sheet with total count and notes per image, without any algorithm or
provisional counts) was prepared
for the supervisor in `outputs/Kyle_review_bundle/` (plus
`outputs/Kyle_review_bundle.zip`; local only). When it comes back, compare all three for the 12 images: algorithm,
provisional, and expert.

**TODO: ask the supervisor which objects count as a sperm.** The answers
decide what the algorithm should count:

| Question | Algorithm today |
|---|---|
| Should **detached heads** (no tail) be counted? | Not counted. A head is only recognized where a tail ends |
| Should **headless tails** in the frame be counted, ignored, or reported separately? | Reported separately as `headless_tail` and not counted |
| How should **sperm cut off by the border** be handled? That covers heads on the edge with little tail, and tails entering from the edge with no head | Heads with less than about 100 px of tail are missed. Edge tails without a head are not counted |
| Should **very faint ("transparent") sperm** be included? | Often below the detection threshold |
| Is there a **standard counting convention** for this preparation? | — |

**Thinning implementation (ZhengTest).** On the same 12 images, OpenCV-contrib's
`cv2.ximgproc.thinning` gave identical counts to the numpy Zhang–Suen used
here, but one head moved to a different object (`docs/Dev_Diary.md`). The
numpy version stays. `scripts/zheng-test.sh` repeats the comparison and must
be rerun after the algorithm is re-tuned against the expert counts.

## Next steps

1. **Non-sperm cells.** Develop a similar deterministic strategy to detect
   and count non-sperm cells (round cells, germ cells, and so on). The main
   task is separating them from debris. The rejected dark-blob and
   round-outline components from the current pipeline (`candidate_pixels.png`
   and the head-candidate diagnostics) are a natural starting point.
2. **Validation set.** Collect more lab images with manual sperm counts and
   measure count error before further tuning.
3. **Higher-contrast imaging, if needed.** The lab **can** produce
   higher-contrast images. This project deliberately starts with the current
   low-contrast images because that requires **no change to lab methodology**.
   If count accuracy, especially for faint tails or cell-versus-debris
   separation, proves insufficient, switching to higher-contrast acquisition
   is the fallback. SCP's stain-based masking already works on that kind of
   input.
