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
