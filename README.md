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

**Status: prerelease.** Counts are provisional. The counting rule comes from
the supervisor, and the first comparison with the supervisor's reference counts
shows work still to do (see
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

1. **Choose folder…** or **Choose images…** (20x phase contrast; file types
   under [Input requirements](#input-requirements)). The images open as a slideshow. Move through them with
   Prev / Next, the arrow keys, or the thumbnails.
2. **Count sperm.** Each image switches to its overlay as soon as it is
   counted. The count shows on its thumbnail.
3. The side panel shows the current image's counts (total sperm, intact,
   tail-less, head-less, total heads, total tails, and barely visible), and a
   table with the total, mean, median, and range of each across the batch. A
   color key under the image explains the overlay.

Every run saves to a new folder, by default
`~/EyeSpySC results/<folder name> <date time>/` ("Change…" picks another
place). It contains `summary.csv`, `batch_stats.csv` and, per image, `original.png`,
`overlay.png`, and `candidate_pixels.png` (the CLI's `--minimal` output).
Earlier results are never overwritten. The magnification is fixed at 20x.

The app runs the bundled `eyespysc` command for the work. Its counts are the
same as the command line's.

## Input requirements

| Requirement | Expected |
|---|---|
| Magnification | **20x objective for all inputs.** Every pixel setting is tuned for 20x |
| Imaging | Grayscale phase contrast (TRANS channel), as currently acquired by the lab |
| Format | `.tif`, `.tiff`, `.png`, `.jpg`, `.jpeg`, or `.bmp` (any letter case). 8-bit or 16-bit (16-bit is scaled to 8-bit); color is converted to gray. TIFF straight from the microscope is best: JPEG compression was never validated |
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
| Overlap | The main open research problem (R1–R4 path search and assignment) | Assumed rare. If tails do connect, the whole mass is highlighted and its heads and tails are counted |
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
6. **Heads the tail test cannot see.** A dark blob with the slender lens shape
   of a sperm head (length at least twice the width, 6.5–14 px wide, at most
   70 px long, smooth outline) is also a head. On a mass it is a head resting on
   a tail, and must be at least 8 px wide so a dark midpiece does not pass. Off
   a mass it is a tail-less sperm, and must keep its shape at a lower darkness
   threshold, where debris clumps and pieces of round cells grow larger and
   rounder. A blob with a pinched waist (touching cells, clumped debris) is not a
   head.

   Every head, from this step or the last, must also be as wide as a head. Its
   half-width at the lower threshold, with holes filled, must be 4–10 px: a plain
   tail end is thinner, and a round cell or a debris sheet is wider. A hollow head
   seen edge-on can be as thin as 3 px, so between 3 and 4 px a head passes only
   with a bright center.

   Debris can hide a head from both tests, but the midpiece beside it stays clear.
   So each tail is followed through its junctions, pairing the segments that turn
   it least (at most 50 degrees). A dark stretch at least 40 px long, reaching
   within 70 px of the tail's end, is a midpiece. If no head lies within 60 px of
   it and the tail's end runs into something wide (half-width above 4.4 px), a head
   is added at that end. A midpiece that ends cleanly adds nothing, because a tail
   that has lost its head keeps its midpiece.
7. **Tails.** Each mass is split at junctions, and the free ends of its long,
   thin branches (at least 40 px, median half-width at most 3.5 px) are counted.
   A tail has two ends and a crossing of two tails leaves four, so a mass holds
   ceil(ends / 2) tails, and never fewer than its heads.
8. **Barely visible tails.** A second pass lowers the bar for the strongest
   pixel of a tail (`ridge_faint_high_k`) and keeps only long, thin, locally
   straight masses that the main pass did not already see.
9. **Categories and count.**

   | Category | What it is | Overlay |
   |---|---|---|
   | Intact | Head and tail | Green mass, red head marker |
   | Tail-less | Head with no tail | Magenta ring |
   | Head-less | Tail with no head | Blue mass |
   | Barely visible | Faint tail, reported separately | Yellow mass |

   A mass holding more than one sperm is orange (`overlap_cluster`), labeled with
   its heads and tails, for example `#7 3H 5T`. Its heads pair with its tails:
   the pairs are intact and the extra tails are head-less.

   **Total sperm = intact + the larger of tail-less and head-less**, for each
   image. A loose head and a loose tail are probably parts of one sperm, so
   adding both would count it twice. This equals the larger of total heads and
   total tails. Barely visible tails are not in the total.

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
  at most 1600 px) and `thumb.png` (240 px) per image, for the app's slideshow.

## Outputs

`<output-root>/summary.csv` holds one row per image: `total_sperm`, `intact`,
`tailless`, `headless`, `total_heads`, `total_tails`, `barely_visible`,
`overlap_clusters`, and noise and threshold values.

`<output-root>/batch_stats.csv` holds one row per count, with its total, mean,
median, minimum, and maximum across the images. Each image's total sperm is
worked out on its own and then summed, so the batch total can differ from
applying the rule to the batch's tail-less and head-less totals.

Each image also gets a folder, `<output-root>/<image-stem>/`, containing:

| File | Contents |
|---|---|
| `original.png` | The input as an 8-bit grayscale PNG, unannotated |
| `overlay.png` | Colored instances, numbered head markers, and the counts with a color key |
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
- crossing tails (one overlap cluster, two heads counted), and a tail crossing a
  sperm (one intact, one head-less);
- debris and round cells (not counted);
- debris in the middle of a tail (not a second head);
- head-less, tail-less, and barely visible sperm, and the total-sperm rule;
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

`EXAMPLE_testis_0007_TRANS.tif` gives **13 sperm**: 12 intact, 1 tail-less, and
1 head-less (13 heads, 13 tails), plus 2 barely visible tails.

## Known limitations

- **Sperm cut off by the image border** are missed when less than about
  100 px of tail is visible. One head on the bottom edge whose tail runs
  through another sperm is also suppressed by the faint-neck rule.
- **Debris on the far end of a tail** looks like a head-at-terminus. It is
  rejected only when the mass also contains a real head with a darker neck.
- **Head-less tails that cross a headed sperm** are included in that sperm's
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
- **Some counted heads are still false.** Before heads were added at midpieces,
  hand labeling the 12 review images found 13 of the 202 counted heads to be false,
  mostly debris or cells of head-like width. Those labels were also used to choose
  the thresholds, and a later review disagreed with four of them, so treat this as
  approximate. Total sperm usually follows total heads, so these errors reach the
  total directly.
- **Heads added at midpieces are inferred and not validated on cauda.** They raise
  the 20x batch total by 15%, and cauda by 21% (1241 to 1498), but no reference
  counts include cauda. By eye, about 4 in 5 of a sample on unseen images had a real
  head beside them. Some land where a tail only runs into debris.
- **The head checks remove some real heads.** On 24 images not used for tuning,
  about 5 of the 25 removed heads looked real, mostly hollow heads where tails
  cross.
- **Some heads are counted twice.** A single sperm lying on a large cell or
  debris can get two heads (`20231002 testis_0008`, `20231215 M3O4_0003`). Asking
  whether a head sits mid-tail does not fix this: it removes more real heads
  (a tail lying across them looks the same) than false ones.
- **Barely visible heads are not detected**, only barely visible tails.
- **Heads lying on another sperm's tail** are recovered only when they are
  lens-shaped and at least 8 px wide.
- **Extremely crowded frames** (for example `20231002 cauda_0035`, with
  hundreds of tangled sperm) are out of scope, and their counts are not
  meaningful. See [Input requirements](#input-requirements).
- **Abnormal sperm lower accuracy.** The head checks assume normal head shapes,
  so unusually thin heads can be missed. Expect lower accuracy on samples known
  to contain abnormal sperm, such as knockout lines, and on images where sperm
  overlap. The app says this on its start screen and on About.
- **Some headless tails may have a curled head** that wasn't recognized (for
  example #5 in `20231215 cauda_0020`). This can make counts slightly low.

## Validation status and open counting rules

**Counting rule, from the supervisor (2026-11-02).**

| Question | Answer |
|---|---|
| Count tails with no head? | Yes |
| Count heads with no tail? | Yes |
| Count faint or out-of-focus sperm? | Yes, every visible instance when counting by hand. For the software, ignore them if it cannot tell |
| Which total? | Intact + the larger of tail-less and head-less |

Still open:

- Are barely visible sperm added to the total? They are reported separately for
  now.
- Is the rule applied to each image or to a whole sample? It is applied to each
  image for now.
- How should sperm cut off by the image border be handled?

**Reference counts.** `outputs/Kyle_review_bundle/count_sheet_supervisor_updated.csv`
(local only) has two totals for the 12 review images, which serve as lower and
upper bounds for testing. `total_count_with_tailless` counts every head, tail,
and intact sperm found, before the total-sperm rule. `total_count` is the lower
figure. The sheet has totals only, so misses and false detections cannot be told
apart. No thresholds have been fitted to these counts; the head checks came from
hand labels of individual heads, with the sheet used only to measure the result.

| Compared with the upper bound (251) | Total | Mean error per image | Correlation | Within ±2 |
|---|---:|---:|---:|---:|
| Intact + tail-less + head-less (like for like) | 261 | 3.17 | 0.93 | 3/12 |
| The same plus barely visible | 281 | 4.00 | 0.90 | 4/12 |
| Heads only (the count before these categories) | 126 | 10.58 | 0.61 | 2/12 |

Total sperm under the rule comes to 228, between the batch bounds of 194 and 251,
and falls inside the bounds on 4 of the 12 images. It is too high on five
(`caput_0014`, `caput_0026`, `testis_0008`, `M3O4_0003`, `testis_0007`), by 1 to 4,
and too low on three (`caput_0016`, `testis_0003` from 20240819, `caput_0023`).

**Object-by-object review (developer, non-expert, 2026-11-04).** Four review images
(`testis_0003` and `testis_0008` from 20231002, `M3O4_0003`, `testis_0007`) were
checked object by object. Against that review, heads missed fell from 11 to 4 of 46
and extra heads went from 3 to 4 when heads were added at midpieces. These images
chose the midpiece rule, so this is optimistic. The review's totals are 12, 18–20,
9–10, and 14, against 12, 20, 11, and 15 from the software. `M3O4` images are
treated as knockout samples and are not used to choose thresholds.

**Provisional (non-expert) counts** for the same 12 images, made by the project's
developer, are in `validation/provisional_counts_2026-10-28.csv` (the only
lab-data file committed to this repository). They total 182, against 126 for the
head-only count the algorithm used on that date.

**Thinning implementation (ZhengTest).** On the same 12 images (2026-11-04),
OpenCV-contrib's `cv2.ximgproc.thinning` gave the same counts as the numpy
Zhang–Suen used here on 11 images and one more on `M3O4_0003` (12 against 11),
and heads moved on two images (`docs/Dev_Diary.md`). The numpy version stays.
`scripts/zheng-test.sh` repeats the comparison and must be rerun after the
algorithm is re-tuned against the reference counts.

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
