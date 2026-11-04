# EyeSpySC development diary

## 2026-10-30: ZhengTest (thinning implementation comparison)

**Question.** SCP's `skeletonize_binary` uses OpenCV-contrib's
`cv2.ximgproc.thinning` when contrib is installed, and its own numpy
Zhang–Suen otherwise. EyeSpySC now always uses the numpy Zhang–Suen (commit
`a74a5d3`). How much would contrib's thinning change the results?

**Method.** `scripts/zheng-test.sh` ran both versions on the 12 images in
`outputs/Kyle_review_bundle/original_files/` (opencv-contrib-python-headless
4.13.0.92, same numpy and Pillow pins). Output: `outputs/runZhengTest/`.

**Result.**
- Sperm counts identical on all 12 images; they also equal the 2026-10-28
  algorithm counts in `validation/provisional_counts_2026-10-28.csv`.
- Instance masks identical pixel for pixel; overlays identical on 11 of 12.
- Skeletons differ: tail lengths shift by up to 7.2 px and straightness values
  change on about 20 of 140 instances. Only 2 images had identical
  `instances.json`.
- Image 05 (`20231215 M3O4_0003`), instance #8: same count (1) but a different
  head. Numpy marks the tail/loop junction on the bottom edge; contrib marks a
  debris clump in the bottom-right corner. Visually the numpy choice looks
  right (non-expert judgment).

**Decision.** Keep the numpy Zhang–Suen version from commit `a74a5d3`. Rerun
the ZhengTest after the supervisor's expert counts arrive and the algorithm is
re-tuned, because retuned thresholds may sit closer to the skeleton
differences.

## 2026-10-30: v0.1.0-rc.1 install test (development machine)

Released `v0.1.0-rc.1` ("Testing Install", commit `a42f1f6`), the first
CLI-only `.deb`. The ZIP downloaded from the GitHub release installed with
`apt` on the development machine. `eyespysc` run on the 12 review-bundle
images reproduced the counts from source (9, 11, 11, 14, 8, 10, 15, 15, 4,
8, 10, 11). This is not the clean-machine check: the machine already had
Python and OpenCV. Finding: `installation.md` did not say to unzip and `cd`
into the folder first; fixed in `v0.1.0-rc.2`.

Decisions: the developer's provisional counts are now committed
(`validation/provisional_counts_2026-10-28.csv`), and EyeSpySC skips the
standard's separate testing-environment folder.

## 2026-10-30: v0.1.0-rc.2 clean-machine install check

The developer installed `v0.1.0-rc.2` from the GitHub release ZIP, following
its `installation.md`, on a fresh Ubuntu VM and on WSL2 Ubuntu. The terminal
version worked correctly on both. This meets the standard's section 10 check
for the CLI-only package. Per Appendix A step 6, the first stable release
still waits for the expert counts and re-validation.

## 2026-10-30: Desktop GUI (v0.1.0-rc.3)

The user picked the Missus Tom style from four theme mock-ups, and that style
is now the house style for all our GUIs (standard section 3). The user's logo
is required in every app (standard principle 7); `Random/Logo.svg` is a
transparent vector trace of `Logo.png`.

Design decisions, all from the user:
- One screen does the whole job. Choosing images opens them as a slideshow;
  Count sperm switches each image to its overlay as it finishes; a side panel
  shows per-image and batch stats.
- 20x is fixed and shown as text, not a control. No crops, overwrite, or
  output-mode options. Each run saves to a new time-stamped folder.
- The GUI ships within 0.1.0 (not 0.2.0 as Appendix A planned).

Implementation: the GUI drives the existing CLI as a one-shot sidecar. The
CLI gained `--json-progress`, `--preview-only`, and a repeatable `--input`.
Counting code is untouched; the 100-image regression batch still matches
`outputs/runFull/summary.csv` exactly. The Tauri `.deb` replaces the
`dpkg-deb` CLI-only package and keeps `/usr/bin/eyespysc`.

## 2026-10-30: rc.3 GUI never showed images (fixed for rc.4)

The user's manual test of rc.3 on WSL: the app opened, but after choosing
images it stayed on "Loading…", with a broken-image icon where the image
should be. Two causes:

1. `@tauri-apps/api` 2.2 (copied from Missus Tom's pins) against the
   `tauri` 2.11 crate. The crate tags channel messages with `index`, the old
   JavaScript expects `id`, so every progress message was queued forever and
   the app never heard of any image. Missus Tom has the same mismatch but uses
   no channels. Fix: JavaScript packages now match the crates
   (`@tauri-apps/api` 2.11.1, `cli` 2.11.5, `plugin-dialog` 2.7.3), crates are
   pinned exactly, and `desktop/test/tauriVersions.test.ts` checks the pairing.
2. Images were passed as bytes over IPC and turned into blob URLs, which
   WebKitGTK did not display. Fix: the window loads PNGs through Tauri's asset
   protocol, allowed only for the preview folder and each results folder.
   `--preview-only` also writes `thumb.png`, so the app no longer resizes
   images itself.

Also: narrow windows (or scaled displays) put Count sperm above the images
instead of below them, and choosing a thumbnail no longer scrolls the page.
The accepted file types are listed on the start screen.

Verified locally with a temporary, uncommitted auto-load build: four real
images loaded, counted 15/20/11/21 (as in the regression baseline), and
overlays and stats displayed.


## 2026-11-02: Four sperm categories

The supervisor defined what to count. Sperm fall into four categories: intact,
tail-less, head-less, and barely visible. Total sperm = intact + the larger of
tail-less and head-less, because a loose head and a loose tail are probably
parts of one sperm. That is also the larger of total heads and total tails.

Changes:

- **Tails.** Each mass now has a tail count, from the free ends of its long,
  thin skeleton branches. A sperm with extra tails crossing it used to count as
  one object; those tails are now head-less sperm.
- **Heads.** Heads used to require a tail ending at them, so a head with no tail
  was invisible. A dark blob shaped like a head (slender lens, smooth, head-sized)
  now counts. Off a mass it is tail-less; on a mass it is a head resting on a tail.
  Hand labeling 100 detections showed 30 false ones (debris clumps, touching round
  cells, cell fragments). Requiring the blob to keep its shape at a lower darkness
  threshold removed 19 of those and lost 5 of the 70 real heads.
- **Barely visible.** A second pass with a lower bar for a tail's strongest pixel
  (`ridge_faint_high_k` = 10). Reported separately, not in the total.
- **Outputs.** New `summary.csv` columns, `batch_stats.csv`, a counts-and-key panel
  on every overlay, and a color key and batch table in the app.

Lowering the main threshold alone does not recover missed sperm: heads stayed at
126–130 across `ridge_high_k` 7–21 on the review images, because merged masses
lose heads. That is why faint tails get their own pass.

All thresholds here were set by inspecting images, not against reference counts,
so they may change. New regression baseline: `outputs/runFull_2026-11-02/`.

## 2026-11-02: False heads in debris-heavy images

Images with many cells and much debris counted too many sperm. Labeling all 222
counted heads by hand on the 12 review images found 32 false ones (and 16 unsure),
and they were not only loose lens shapes. The original tail-end test also produced
them: plain tail ends with no head, and markers on round cells or debris.

Three checks, all thresholds from those labels:

- **Width.** Half-width at the head, at the lower darkness threshold with holes
  filled, must be 4–10 px. A plain tail is thinner; a cell is wider.
- **Hollow heads.** The first version removed real hollow heads seen edge-on,
  mostly in cauda, which the review images do not include. Only a check on other
  images showed this. They are as thin as thick tails (3.3–3.8 px) and have no
  enclosed hole, but they do have a bright center (about -7 to -11 noise units,
  against -3 to -5 for tails). Between 3 and 4 px a head now needs that bright core.
- **Waist.** A loose lens with a pinched waist is touching cells or debris.

Rejected: a test for heads sitting mid-tail. At 135 degrees or more between the two
arms leaving a head, it removed 5 real heads to catch 3 false ones, because a real
head with a tail across it looks the same.

Result on the review images: 19 of the 32 false heads removed, 1 of 174 real heads
lost. Those labels chose the thresholds, so this is optimistic. On 24 further images,
25 of 705 heads were removed, and about 5 of those looked real.

New regression baseline: `outputs/runFull_2026-11-02b/`.

## 2026-11-04: Heads near debris

An object-by-object review of four images showed sperm lost where a head sits in or
beside debris: the head fails the tail-end test, the mass reads as one head-less
tail, and whole sperm disappear from the total. Direction-paired tail counting alone
did not help. It took the total only part of the way, because total sperm is the
larger of heads and tails, and it inflated crowded cauda (74 to 194, or 110 in a
stricter form).

What does separate these cases is the midpiece, a dark stretch at the head end of
the tail that stays visible when the head does not. Tails are now followed through
junctions by direction (the idea is from SCP's `junction_transitions`; SCP's full
resolver was built on stained color images and has not established real-image
accuracy), and a midpiece with no head near it adds one.

Two things went wrong first, both caught by checking on other images:

- **A midpiece does not prove a head.** Tails that lost their heads keep theirs, and
  caput has many. Heads jumped past the upper bound there until a head was required
  to lie at a tail end that runs into something wide. Clean blunt ends stay head-less.
- **Removing heads did more harm than good.** Dropping unexplained heads sitting
  mid-tail fixed `M3O4_0003`, but on unseen cauda most of the sampled removals were
  real heads with a faint tail lying across them. This matches the mid-tail test
  rejected on 2026-11-02. The removal step was dropped.

Result: on the four reviewed images, heads missed fell from 11 to 4 of 46 and extra
heads went from 3 to 4. Against the count sheet it is close to neutral: mean accuracy
of the rule total against the bounds went from 89.1% to 88.6%, with counts now more
often above the upper bound than below the lower one. Over the 94 20x images the
total went from 2425 to 2788, and cauda from 1241 to 1498. No reference counts cover
cauda, so that rise is unconfirmed; by eye, about 4 in 5 of a sample of added heads
on unseen images were beside a real head.

ZhengTest rerun: counts match on 11 of 12 images, `M3O4_0003` gives 12 with contrib
against 11, and heads moved on two images. The numpy thinning stays.

New regression baseline: `outputs/runFull_2026-11-04/`.
