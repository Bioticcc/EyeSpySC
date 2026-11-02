"""Deterministic sperm highlighting and counting for low-contrast grayscale images.

EyeSpySC is an offshoot of Sperm Color Pixels (SCP). It reuses SCP's
local-background darkness idea and skeleton helpers, but replaces the brown
stain color gate (which needs RGB Ward images) with a multi-scale Hessian ridge
filter that finds faint thin dark tails in grayscale phase-contrast images.

Sperm are intact (head and tail), tail-less (head only), head-less (tail only),
or barely visible. A loose head and a loose tail are probably parts of one sperm,
so total sperm = intact + the larger of tail-less and head-less. When one
connected mass holds several sperm, the whole mass is highlighted as an overlap
cluster and its heads and tails are still counted individually. Barely visible
tails are reported separately and are not in the total.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image, UnidentifiedImageError

from . import __version__
from .scp_helpers import (
    prune_skeleton_endpoints,
    remove_small_components,
    zhang_suen_thinning,
)

# Written by scripts/build-linux-sidecars.sh into packaged builds only.
BUILD_REVISION_FILE = Path(__file__).resolve().parent / "build_revision.txt"

IMAGE_EXTS = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp"}
# Thresholds below were tuned on the 2048x1536 example image; lengths and areas
# scale up for frames with a longer side than this reference.
REFERENCE_LONG_SIDE = 2048.0
REFERENCE_MAGNIFICATION = 20.0
# --preview-only images are downscaled to these long sides; the app shows them
# in a window and a thumbnail strip, not at full resolution.
PREVIEW_LONG_SIDE = 1600
THUMB_LONG_SIDE = 240

# The desktop app's color key repeats these (a test keeps them equal).
INTACT_COLOR = (0, 220, 90)
CLUSTER_COLOR = (255, 140, 0)
HEADLESS_COLOR = (0, 170, 255)
TAILLESS_COLOR = (230, 70, 230)
BARELY_VISIBLE_COLOR = (240, 220, 60)
HEAD_COLOR = (255, 40, 40)

COUNT_COLUMNS = (
    "total_sperm",
    "intact",
    "tailless",
    "headless",
    "total_heads",
    "total_tails",
    "barely_visible",
)


@dataclass
class Settings:
    # Objective magnification of the input relative to the reference images all
    # pixel settings below were tuned on. Every length scales by this ratio.
    magnification: float = REFERENCE_MAGNIFICATION
    relief_contrast: bool = False  # set by magnification presets (see settings_for_magnification)
    background_sigma: float = 40.0
    ridge_sigmas: tuple[float, ...] = (1.5, 2.5)
    # Hysteresis thresholds in robust-sigma units of the ridge response
    # (median + k * MAD). Background pixels dominate both statistics, so the
    # thresholds do not drift with how many sperm or how much debris is present.
    ridge_low_k: float = 2.1
    ridge_high_k: float = 21.0
    # Tails with no pixel reaching ridge_high_k but one reaching this are barely visible.
    ridge_faint_high_k: float = 10.0
    ridge_close_px: int = 5
    head_dark_noise_k: float = 5.0
    head_core_px: int = 7  # opening diameter; strips midpiece/tail, keeps head cores
    # Second, thinner pass for slender side-on heads. Accepted heads from both
    # passes are merged (same dark blob or within head_merge_px = one head).
    thin_head_core_px: int = 5
    # Thin-pass candidates must have no other attached skeleton segment at least
    # this long; otherwise a dark midpiece segment can pass for a head.
    min_side_branch: float = 15.0
    head_merge_px: float = 15.0
    head_group_px: int = 11  # cores closer than this merge into one candidate
    min_head_area: int = 40
    max_head_area: int = 2500
    min_tail_length: float = 100.0
    max_tail_halfwidth: float = 3.5
    min_local_straightness: float = 0.9  # median chord/arc over straightness_window
    straightness_window: float = 30.0
    # Length of the skeleton network a head's tail joins, and of a branch that
    # counts as a tail end when counting the tails in a mass.
    min_tail_branch: float = 40.0
    min_tail_segment: float = 12.0  # first segment leaving the head, before any junction
    min_branch_straightness: float = 0.5
    neck_length: float = 30.0
    # Only used to break ties inside a multi-head mass: a candidate whose neck is
    # both faint in absolute terms and much fainter than the darkest neck in the
    # same mass is treated as debris on a tail end, not a second head.
    faint_neck_darkness: float = 5.0
    faint_neck_ratio: float = 0.5
    prune_iterations: int = 3
    # A dark blob with no tail of its own is a head only if it has the slender
    # lens shape of a sperm head. Round cells and clumped debris are too round,
    # too wide, or too ragged. Sizes are of the blob's minimum-area rectangle.
    lens_min_area: int = 120
    lens_max_area: int = 450
    lens_min_aspect: float = 2.0
    lens_min_width: float = 6.5
    lens_max_width: float = 14.0
    lens_max_length: float = 70.0
    lens_min_solidity: float = 0.78
    # On a mass a dark midpiece stretch can look like a thin lens; heads are wider.
    lens_on_mass_min_width: float = 8.0
    # A loose head keeps its shape at a lower darkness threshold. A debris clump or
    # a piece of a round cell grows there into something larger and rounder.
    lens_faint_darkness: float = 2.5
    lens_faint_max_growth: float = 1.8
    lens_faint_min_aspect: float = 1.9


@dataclass
class HeadCandidate:
    xy: list[float]
    core_area_px: int
    tail_branches: int  # tail-like skeleton segments touching the core
    terminating_branches: int  # of those, segments with a free endpoint at the core
    side_branches: int  # other attached segments >= min_side_branch (excluding the tail)
    neck_darkness: float  # mean local darkness / noise along the first neck_length px of tail
    core_radius_px: float  # largest inscribed radius of the core group
    dark_blob_id: int  # dark blob containing the core; used only to place the head marker
    core_px: int = 0  # opening diameter of the pass that produced this candidate
    accepted: bool = False
    reason: str = ""


@dataclass
class SpermInstance:
    instance_id: int
    kind: str  # "intact" | "tailless" | "headless" | "overlap_cluster" | "barely_visible"
    head_count: int
    tail_count: int
    bbox_xywh: list[int]
    area_px: int
    tail_length_px: float
    straightness: float
    local_straightness: float
    path_fraction: float
    heads_xy: list[list[float]] = field(default_factory=list)
    head_candidates: list[HeadCandidate] = field(default_factory=list)


def skeletonize(mask: NDArray[Any]) -> NDArray[Any]:
    """Zhang-Suen thinning, always.

    SCP's skeletonize_binary switches to cv2.ximgproc.thinning when
    OpenCV-contrib is installed, which changes counts. Every validated count
    used Zhang-Suen, so call it directly whatever OpenCV build is present.
    """
    return zhang_suen_thinning(mask)


def scale_factor(width: int, height: int, magnification: float = REFERENCE_MAGNIFICATION) -> float:
    # Like SCP: only enlarge kernels for bigger frames. Smaller crops at the same
    # magnification keep the reference pixel sizes. Higher magnification makes
    # every structure proportionally larger in pixels.
    frame = max(1.0, max(width, height) / REFERENCE_LONG_SIDE)
    return frame * magnification / REFERENCE_MAGNIFICATION


def load_gray(path: Path) -> NDArray[Any]:
    try:
        with Image.open(path) as img:
            if img.mode.startswith("I;16") or img.mode == "I":
                # 16-bit captures: drop the low byte so brightness and contrast
                # land in the same range as the lab's 8-bit TIFFs. convert("L")
                # would clip everything above 255 to white.
                data = np.asarray(img).astype(np.uint32)
                return np.clip(data >> 8, 0, 255).astype(np.uint8)
            return np.asarray(img.convert("L"))
    except (UnidentifiedImageError, OSError) as exc:
        raise RuntimeError(f"Could not read image: {path}") from exc


def flatten_background(gray: NDArray[Any], sigma: float) -> tuple[NDArray[Any], float]:
    """Return local darkness (background minus image) and robust noise sigma."""
    image = gray.astype(np.float32)
    background = cv2.GaussianBlur(image, (0, 0), sigmaX=sigma, sigmaY=sigma)
    flat: NDArray[Any] = image - background
    noise = float(1.4826 * np.median(np.abs(flat - np.median(flat))))
    return -flat, max(noise, 1e-3)


def ridge_response(gray: NDArray[Any], sigmas: tuple[float, ...]) -> NDArray[Any]:
    """Multi-scale Hessian response for thin dark lines on a bright background."""
    image = gray.astype(np.float32)
    response = np.zeros_like(image)
    for sigma in sigmas:
        smooth = cv2.GaussianBlur(image, (0, 0), sigmaX=sigma, sigmaY=sigma)
        dxx = cv2.Sobel(smooth, cv2.CV_32F, 2, 0, ksize=3)
        dyy = cv2.Sobel(smooth, cv2.CV_32F, 0, 2, ksize=3)
        dxy = cv2.Sobel(smooth, cv2.CV_32F, 1, 1, ksize=3)
        half_trace = (dxx + dyy) / 2.0
        root = np.sqrt(((dxx - dyy) / 2.0) ** 2 + dxy**2)
        across = half_trace + root  # large positive across a dark line
        along = half_trace - root  # near zero along a line, large for blobs
        line = np.clip(across - 0.5 * np.abs(along), 0, None) * sigma * sigma
        response = np.maximum(response, line)
    return response


def hysteresis_mask(response: NDArray[Any], low: float, high: float) -> NDArray[Any]:
    weak = (response >= low).astype(np.uint8)
    n_labels, labels = cv2.connectedComponents(weak, connectivity=8)
    keep = np.zeros(n_labels, dtype=bool)
    keep[np.unique(labels[response >= high])] = True
    keep[0] = False
    mask: NDArray[Any] = keep[labels].astype(np.uint8) * 255
    return mask


def fill_holes(mask: NDArray[Any]) -> NDArray[Any]:
    """Fill background regions not connected to the image border."""
    padded = np.pad((mask > 0).astype(np.uint8) * 255, 1)
    flood = padded.copy()
    cv2.floodFill(flood, None, (0, 0), 255)
    holes = cv2.bitwise_not(flood)[1:-1, 1:-1]
    return cv2.bitwise_or(mask, holes)


def build_masks(gray: NDArray[Any], settings: Settings) -> dict[str, Any]:
    height, width = gray.shape
    scale = scale_factor(width, height, settings.magnification)
    dark, noise = flatten_background(gray, settings.background_sigma * scale)
    response = ridge_response(gray, tuple(s * scale for s in settings.ridge_sigmas))
    median = float(np.median(response))
    spread = float(1.4826 * np.median(np.abs(response - median))) or 1e-3
    low = median + settings.ridge_low_k * spread
    high = median + settings.ridge_high_k * spread
    ridge = hysteresis_mask(response, low, high)
    close_px = max(3, int(round(settings.ridge_close_px * scale)) | 1)
    ridge = cv2.morphologyEx(
        ridge, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_px, close_px))
    )

    smooth_dark = cv2.GaussianBlur(dark, (0, 0), sigmaX=1.0, sigmaY=1.0)
    blob: NDArray[Any]
    if settings.relief_contrast:
        # Higher magnification shows relief contrast: heads are hollow outlines
        # with one dark and one bright edge. Take contrast of either sign and
        # fill enclosed holes so an outlined head becomes a solid blob.
        blob = (np.abs(smooth_dark) >= settings.head_dark_noise_k * noise).astype(np.uint8) * 255
        blob = cv2.morphologyEx(
            blob, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        )
        blob = fill_holes(blob)
    else:
        blob = (smooth_dark >= settings.head_dark_noise_k * noise).astype(np.uint8) * 255
    blob = cv2.morphologyEx(
        blob, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    )
    blob = remove_small_components(blob, max(1, int(round(settings.min_head_area * scale * scale))))
    return {
        "ridge": ridge,
        "blob": blob,
        "sperm_pixels": cv2.bitwise_or(ridge, blob),
        "darkness": smooth_dark / noise,
        "response": response,
        "ridge_faint_high": median + settings.ridge_faint_high_k * spread,
        "noise": noise,
        "ridge_low": low,
        "ridge_high": high,
    }


def _skeleton_neighbors(coords_yx: NDArray[Any]) -> list[list[int]]:
    coord_to_idx = {(int(y), int(x)): idx for idx, (y, x) in enumerate(coords_yx)}
    neighbors: list[list[int]] = [[] for _ in range(len(coords_yx))]
    for idx, (y, x) in enumerate(coords_yx):
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    other = coord_to_idx.get((int(y) + dy, int(x) + dx))
                    if other is not None:
                        neighbors[idx].append(other)
    return neighbors


def longest_skeleton_path(skeleton: NDArray[Any]) -> NDArray[Any]:
    """Ordered (N, 2) yx coordinates of the longest geodesic skeleton path.

    Same double-sweep idea as SCP's skeleton_longest_path, but returns the
    ordered points so arc length and chord can be measured.
    """
    coords_yx = np.argwhere(skeleton > 0)
    if len(coords_yx) == 0:
        return np.zeros((0, 2), dtype=np.int64)
    neighbors = _skeleton_neighbors(coords_yx)

    def sweep(start: int) -> tuple[int, list[int]]:
        dist = np.full(len(coords_yx), np.inf)
        parent = [-1] * len(coords_yx)
        dist[start] = 0.0
        frontier = [start]
        # Small graphs: Bellman-style relaxation with step weights 1 / sqrt(2).
        while frontier:
            next_frontier = []
            for current in frontier:
                cy, cx = coords_yx[current]
                for other in neighbors[current]:
                    oy, ox = coords_yx[other]
                    step = 1.4142135 if (oy != cy and ox != cx) else 1.0
                    if dist[current] + step < dist[other] - 1e-9:
                        dist[other] = dist[current] + step
                        parent[other] = current
                        next_frontier.append(other)
            frontier = next_frontier
        reachable = np.where(np.isfinite(dist))[0]
        far = int(reachable[np.argmax(dist[reachable])])
        path = []
        node = far
        while node != -1:
            path.append(node)
            node = parent[node]
        return far, path

    endpoints = [idx for idx, items in enumerate(neighbors) if len(items) <= 1]
    first, _ = sweep(endpoints[0] if endpoints else 0)
    _, path = sweep(first)
    return coords_yx[path]


def path_length(path_yx: NDArray[Any]) -> float:
    if len(path_yx) < 2:
        return float(len(path_yx))
    return float(np.sum(np.linalg.norm(np.diff(path_yx.astype(np.float32), axis=0), axis=1)))


def local_straightness(path_yx: NDArray[Any], window: float) -> float:
    """Median chord/arc ratio over sliding windows along the path.

    Tails are locally straight even where two of them cross; debris outlines and
    clumps curl at every scale. Global chord/arc would penalise crossings.
    """
    if len(path_yx) < 2:
        return 0.0
    steps = np.linalg.norm(np.diff(path_yx.astype(np.float32), axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(steps)])
    span = max(2, int(round(window)))
    if len(path_yx) <= span:
        return float(
            np.linalg.norm((path_yx[0] - path_yx[-1]).astype(np.float32)) / max(arc[-1], 1.0)
        )
    ratios = [
        float(np.linalg.norm((path_yx[a + span] - path_yx[a]).astype(np.float32)))
        / max(float(arc[a + span] - arc[a]), 1.0)
        for a in range(0, len(path_yx) - span, max(1, span // 3))
    ]
    return float(np.median(ratios))


def crossing_number(binary: NDArray[Any]) -> NDArray[Any]:
    """0->1 transitions around each pixel's 8-neighbourhood (3+ = true junction).

    Unlike a plain neighbour count this ignores staircase corners on thin
    8-connected skeletons.
    """
    padded = np.pad((binary > 0).astype(np.int8), 1)
    h, w = binary.shape
    ring = [(0, 1), (0, 2), (1, 2), (2, 2), (2, 1), (2, 0), (1, 0), (0, 0)]
    neighbors = [padded[dy : dy + h, dx : dx + w] for dy, dx in ring]
    return cast(
        NDArray[Any],
        sum(
            ((neighbors[i] == 0) & (neighbors[(i + 1) % 8] == 1)).astype(np.int16) for i in range(8)
        ),
    )


def find_heads(
    component: NDArray[Any],
    skeleton: NDArray[Any],
    blob: NDArray[Any],
    darkness: NDArray[Any],
    settings: Settings,
    scale: float,
    core_px: int,
) -> list[HeadCandidate]:
    """Head candidates: thick dark cores, scored by how tail branches attach.

    Opening the dark-blob mask strips the thinner midpiece and tail, leaving
    head cores (and thick debris). Nearby cores are grouped so a head and a
    thick midpiece segment form one candidate. For each candidate the function
    records the tail-like skeleton branches touching it, how many of those
    actually terminate at it, and the darkness of the neck (first stretch of
    tail, i.e. the midpiece). select_heads() makes the decision.
    """
    core_px = max(3, int(round(core_px * scale)) | 1)
    dark_blobs = ((blob > 0) & (component > 0)).astype(np.uint8)
    cores = cv2.morphologyEx(
        dark_blobs, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (core_px, core_px))
    )
    if not np.any(cores):
        return []
    # Nearby cores (head + a thick midpiece segment) form one candidate.
    group_px = max(3, int(round(settings.head_group_px * scale)) | 1)
    grouped = cv2.dilate(cores, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (group_px, group_px)))
    n_groups, group_labels = cv2.connectedComponents(grouped, connectivity=8)
    group_labels[cores == 0] = 0
    _, blob_labels = cv2.connectedComponents(dark_blobs, connectivity=8)

    grow_px = max(3, int(round(5 * scale)) | 1)
    grow = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (grow_px, grow_px))
    remainder = ((skeleton > 0) & (cv2.dilate(cores, grow) == 0)).astype(np.uint8)
    # Split the remaining skeleton at junctions so crossings and side spurs become
    # separate segments; networks keep track of what each segment connects to.
    kernel = np.ones((3, 3), dtype=np.uint8)
    junctions = cv2.dilate(
        ((remainder > 0) & (crossing_number(remainder) >= 3)).astype(np.uint8), kernel
    )
    segments = ((remainder > 0) & (junctions == 0)).astype(np.uint8)
    _, segment_labels, segment_stats, _ = cv2.connectedComponentsWithStats(segments, connectivity=8)
    _, network_labels, network_stats, _ = cv2.connectedComponentsWithStats(
        remainder, connectivity=8
    )
    free_ends = (segments > 0) & (crossing_number(segments) <= 1)

    min_branch = settings.min_tail_branch * scale
    min_segment = settings.min_tail_segment * scale
    neck_reach = settings.neck_length * scale + 2.0
    terminus_reach = 5.0 * scale + 1.0

    segment_info: dict[int, tuple[bool, NDArray[Any]]] = {}

    def describe(segment: int) -> tuple[bool, NDArray[Any]]:
        """(tail_like, free endpoint yx array) for one skeleton segment."""
        if segment not in segment_info:
            pixels = segment_labels == segment
            ys, xs = np.nonzero(pixels)
            ends = np.argwhere(pixels & free_ends)
            network = int(network_labels[ys[0], xs[0]])
            tail_like = (
                len(ys) >= min_segment and network_stats[network, cv2.CC_STAT_AREA] >= min_branch
            )
            if tail_like and len(ys) >= 2 * min_segment:
                y0, x0 = ys.min(), xs.min()
                local = np.zeros((ys.max() - y0 + 1, xs.max() - x0 + 1), dtype=np.uint8)
                local[ys - y0, xs - x0] = 1
                path = longest_skeleton_path(local)
                chord = float(np.linalg.norm((path[0] - path[-1]).astype(np.float32)))
                tail_like = chord / max(path_length(path), 1.0) >= settings.min_branch_straightness
            segment_info[segment] = (tail_like, ends)
        return segment_info[segment]

    min_area = settings.min_head_area * scale * scale
    max_area = settings.max_head_area * scale * scale
    candidates: list[HeadCandidate] = []
    for group_idx in range(1, n_groups):
        core = (group_labels == group_idx).astype(np.uint8)
        area = int(np.count_nonzero(core))
        if not (min_area <= area <= max_area):
            continue
        ring = cv2.dilate(cv2.dilate(core, grow), kernel) > 0
        touching = {int(v) for v in np.unique(segment_labels[ring]) if v > 0}
        tails = [seg for seg in touching if describe(seg)[0]]
        from_core = cv2.distanceTransform(1 - core, cv2.DIST_L2, 3)
        terminating = [
            seg
            for seg in tails
            if any(from_core[int(y), int(x)] <= terminus_reach for y, x in describe(seg)[1])
        ]

        min_side = settings.min_side_branch * scale
        side = [
            seg
            for seg in touching
            if seg not in terminating[:1] and segment_stats[seg, cv2.CC_STAT_AREA] >= min_side
        ]

        neck_darkness = 0.0
        if len(terminating) == 1:
            neck = (network_labels == network_labels[segment_labels == terminating[0]][0]) & (
                from_core <= neck_reach
            )
            if np.any(neck):
                neck_darkness = float(darkness[neck].mean())

        # Thickest point of the core marks the head rather than the core centroid.
        inside = cv2.distanceTransform(core, cv2.DIST_L2, 3)
        cy, cx = np.unravel_index(int(np.argmax(inside)), inside.shape)
        candidates.append(
            HeadCandidate(
                xy=[float(cx), float(cy)],
                core_area_px=area,
                tail_branches=len(tails),
                terminating_branches=len(terminating),
                side_branches=len(side),
                neck_darkness=round(neck_darkness, 2),
                core_radius_px=round(float(inside[cy, cx]), 2),
                dark_blob_id=int(blob_labels[cy, cx]),
                core_px=core_px,
            )
        )
    return candidates


def drop_faint_necks(accepted: list[HeadCandidate], settings: Settings) -> None:
    """Within one multi-head mass, reject heads whose neck is faint and much
    fainter than the darkest neck (debris on a tail end, not a midpiece)."""
    if len(accepted) < 2:
        return
    darkest = max(c.neck_darkness for c in accepted)
    for cand in accepted:
        if (
            cand.neck_darkness < settings.faint_neck_darkness
            and cand.neck_darkness < settings.faint_neck_ratio * darkest
        ):
            cand.accepted = False
            cand.reason = "faint_neck_in_multi_head_mass"


def select_heads(candidates: list[HeadCandidate], settings: Settings, strict: bool = False) -> None:
    """Mark accepted heads in place and record why others were rejected.

    strict (thin-core pass) additionally rejects candidates with any other
    sizeable attached segment.
    """
    for cand in candidates:
        if cand.tail_branches == 0:
            cand.reason = "no_tail_attached"
        elif cand.terminating_branches == 0:
            cand.reason = "touches_side_of_tail"
        elif cand.terminating_branches > 1:
            cand.reason = "tail_passes_through"
        elif strict and cand.side_branches > 0:
            cand.reason = "thin_core_has_side_branch"
        else:
            cand.accepted = True
            cand.reason = "tail_terminus"
    # Display only: a thick midpiece core can win the terminus test while the
    # true head is a separate, thicker core in the same dark blob.
    for cand in candidates:
        if not cand.accepted:
            continue
        siblings = [
            other
            for other in candidates
            if other.reason == "no_tail_attached"
            and other.dark_blob_id == cand.dark_blob_id
            and other.core_radius_px > cand.core_radius_px
        ]
        if siblings:
            cand.xy = list(max(siblings, key=lambda c: c.core_radius_px).xy)


def count_tails(
    skeleton: NDArray[Any], halfwidth: NDArray[Any], settings: Settings, scale: float
) -> int:
    """Tails in one mass, from the free ends of its long, thin skeleton branches.

    A tail has two ends and a crossing of two tails leaves four, so a mass holds
    ceil(ends / 2) tails. Short spurs and branches through thick debris have no
    say. A mass with no qualifying end (a closed loop) still holds one tail.
    """
    binary = (skeleton > 0).astype(np.uint8)
    crossings = crossing_number(binary)
    junctions = cv2.dilate(
        ((binary > 0) & (crossings >= 3)).astype(np.uint8), np.ones((3, 3), dtype=np.uint8)
    )
    branches = ((binary > 0) & (junctions == 0)).astype(np.uint8)
    n_branches, labels, stats, _ = cv2.connectedComponentsWithStats(branches, connectivity=8)
    free_ends = (binary > 0) & (crossings <= 1)
    ends = 0
    for branch in range(1, n_branches):
        if stats[branch, cv2.CC_STAT_AREA] < settings.min_tail_branch * scale:
            continue
        pixels = labels == branch
        if np.median(halfwidth[pixels]) <= settings.max_tail_halfwidth * scale:
            ends += int(np.count_nonzero(pixels & free_ends))
    return max(1, (ends + 1) // 2)


def outline_shape(local: NDArray[Any]) -> tuple[NDArray[Any], float, float]:
    """(outer contour, length, width) of a binary region, from its minimum-area rectangle."""
    contours, _ = cv2.findContours(local, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contour = max(contours, key=cv2.contourArea)
    _, sides, _ = cv2.minAreaRect(contour)
    return contour, max(sides), max(min(sides), 1.0)


def find_lens_blobs(blob: NDArray[Any], settings: Settings, scale: float) -> list[dict[str, Any]]:
    """Dark blobs shaped like a sperm head: slender, smooth, and head-sized."""
    n_blobs, labels, stats, centroids = cv2.connectedComponentsWithStats(blob, connectivity=8)
    lenses = []
    for label in range(1, n_blobs):
        x, y, w, h, area = (int(v) for v in stats[label])
        if not settings.lens_min_area * scale**2 <= area <= settings.lens_max_area * scale**2:
            continue
        local = (labels[y : y + h, x : x + w] == label).astype(np.uint8)
        contour, length, width = outline_shape(local)
        hull_area = max(float(cv2.contourArea(cv2.convexHull(contour))), 1.0)
        if (
            length / width >= settings.lens_min_aspect
            and settings.lens_min_width * scale <= width <= settings.lens_max_width * scale
            and length <= settings.lens_max_length * scale
            and cv2.contourArea(contour) / hull_area >= settings.lens_min_solidity
        ):
            ys, xs = np.nonzero(local)
            lenses.append(
                {
                    "xy": [float(centroids[label][0]), float(centroids[label][1])],
                    "bbox": [x, y, w, h],
                    "area": area,
                    "width": width,
                    "ys": ys + y,
                    "xs": xs + x,
                }
            )
    return lenses


def keeps_lens_shape_when_faint(
    lens: dict[str, Any], faint_labels: NDArray[Any], faint_stats: NDArray[Any], settings: Settings
) -> bool:
    owners = faint_labels[lens["ys"], lens["xs"]]
    if not np.any(owners):
        return False
    label = int(np.bincount(owners[owners > 0]).argmax())
    x, y, w, h, area = (int(v) for v in faint_stats[label])
    if area > settings.lens_faint_max_growth * lens["area"]:
        return False
    local = (faint_labels[y : y + h, x : x + w] == label).astype(np.uint8)
    _, length, width = outline_shape(local)
    return length / width >= settings.lens_faint_min_aspect


def add_lens_heads(
    instances: list[SpermInstance],
    instance_map: NDArray[Any],
    masks: dict[str, Any],
    settings: Settings,
    scale: float,
) -> None:
    """Add heads the tail-terminus test cannot see, in place.

    A lens-shaped blob on a mass is a head resting on a tail; one with no mass
    is a tail-less sperm.
    """
    merge_px = settings.head_merge_px * scale
    faint = cv2.morphologyEx(
        (masks["darkness"] >= settings.lens_faint_darkness).astype(np.uint8),
        cv2.MORPH_OPEN,
        np.ones((3, 3), dtype=np.uint8),
    )
    _, faint_labels, faint_stats, _ = cv2.connectedComponentsWithStats(faint, connectivity=8)
    for lens in find_lens_blobs(masks["blob"], settings, scale):
        ys, xs = lens["ys"], lens["xs"]
        owners = instance_map[ys, xs]
        owner = int(np.bincount(owners).argmax()) if np.any(owners) else 0
        if owner == 0:
            if not keeps_lens_shape_when_faint(lens, faint_labels, faint_stats, settings):
                continue
            instance_id = len(instances) + 1
            instance_map[ys, xs] = instance_id
            instances.append(
                SpermInstance(
                    instance_id=instance_id,
                    kind="tailless",
                    head_count=1,
                    tail_count=0,
                    bbox_xywh=lens["bbox"],
                    area_px=lens["area"],
                    tail_length_px=0.0,
                    straightness=0.0,
                    local_straightness=0.0,
                    path_fraction=0.0,
                    heads_xy=[[round(lens["xy"][0], 1), round(lens["xy"][1], 1)]],
                )
            )
            continue
        mass = instances[owner - 1]
        if lens["width"] < settings.lens_on_mass_min_width * scale or any(
            np.min(np.hypot(xs - hx, ys - hy)) <= merge_px for hx, hy in mass.heads_xy
        ):
            continue
        mass.heads_xy.append([round(lens["xy"][0], 1), round(lens["xy"][1], 1)])
        mass.head_count += 1
        mass.head_candidates.append(
            HeadCandidate(
                xy=lens["xy"],
                core_area_px=lens["area"],
                tail_branches=0,
                terminating_branches=0,
                side_branches=0,
                neck_darkness=0.0,
                core_radius_px=0.0,
                dark_blob_id=-1,
                accepted=True,
                reason="lens_shape",
            )
        )


def measure_tail_mass(
    component: NDArray[Any], settings: Settings, scale: float
) -> dict[str, Any] | None:
    """Skeleton measurements of a connected mass, or None if it holds no tail.

    A mass holds a tail when its longest path is long, thin, and locally straight.
    """
    min_tail = settings.min_tail_length * scale
    skeleton = prune_skeleton_endpoints(
        skeletonize(component), max(1, int(round(settings.prune_iterations * scale)))
    )
    if not np.any(skeleton):
        return None
    path = longest_skeleton_path(skeleton)
    length = path_length(path)
    if length < min_tail:
        return None
    chord = float(np.linalg.norm((path[0] - path[-1]).astype(np.float32)))
    local = local_straightness(path, settings.straightness_window * scale)
    halfwidth = cv2.distanceTransform((component > 0).astype(np.uint8), cv2.DIST_L2, 3)
    thin_length = float(
        np.count_nonzero(halfwidth[path[:, 0], path[:, 1]] <= settings.max_tail_halfwidth * scale)
    )
    if thin_length < min_tail or local < settings.min_local_straightness:
        return None
    return {
        "skeleton": skeleton,
        "halfwidth": halfwidth,
        "length": length,
        "straightness": chord / max(length, 1.0),
        "local_straightness": local,
        "path_fraction": len(path) / max(1, int(np.count_nonzero(skeleton))),
    }


def add_barely_visible(
    instances: list[SpermInstance],
    instance_map: NDArray[Any],
    masks: dict[str, Any],
    settings: Settings,
    scale: float,
) -> None:
    """Add tails too faint for the main pass, in place, as their own kind.

    The same low threshold and shape tests apply, with a lower bar for the
    strongest pixel. Anything the main pass already saw (accepted or rejected)
    is excluded, and so is anything touching a counted mass.
    """
    close_px = max(3, int(round(settings.ridge_close_px * scale)) | 1)
    faint = cv2.morphologyEx(
        hysteresis_mask(masks["response"], masks["ridge_low"], masks["ridge_faint_high"]),
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_px, close_px)),
    )
    height, width = faint.shape
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(faint, connectivity=8)
    min_tail = settings.min_tail_length * scale
    pad = 2
    for label_idx in range(1, n_labels):
        x, y, w, h, area = (int(v) for v in stats[label_idx])
        if max(w, h) < min_tail * 0.5:
            continue
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(width, x + w + pad), min(height, y + h + pad)
        region = labels[y0:y1, x0:x1] == label_idx
        if np.any(masks["ridge"][y0:y1, x0:x1][region]) or np.any(
            instance_map[y0:y1, x0:x1][region]
        ):
            continue
        component = region.astype(np.uint8) * 255
        mass = measure_tail_mass(component, settings, scale)
        if mass is None:
            continue
        instance_id = len(instances) + 1
        instance_map[y0:y1, x0:x1][region] = instance_id
        instances.append(
            SpermInstance(
                instance_id=instance_id,
                kind="barely_visible",
                head_count=0,
                tail_count=count_tails(mass["skeleton"], mass["halfwidth"], settings, scale),
                bbox_xywh=[x, y, w, h],
                area_px=area,
                tail_length_px=round(mass["length"], 1),
                straightness=round(mass["straightness"], 3),
                local_straightness=round(mass["local_straightness"], 3),
                path_fraction=round(mass["path_fraction"], 3),
            )
        )


def classify_mass(head_count: int, tail_count: int) -> str:
    if head_count == 0 and tail_count == 1:
        return "headless"
    if head_count == 1 and tail_count == 1:
        return "intact"
    return "overlap_cluster"


def count_totals(instances: list[SpermInstance]) -> dict[str, int]:
    """Counts for one image. Total sperm = intact + max(tail-less, head-less).

    Because intact + tail-less is every head and intact + head-less is every tail,
    that is also the larger of total heads and total tails. Barely visible tails
    are counted on their own and join nothing else.
    """
    counted = [i for i in instances if i.kind != "barely_visible"]
    total_heads = sum(i.head_count for i in counted)
    total_tails = sum(i.tail_count for i in counted)
    intact = sum(min(i.head_count, i.tail_count) for i in counted)
    tailless, headless = total_heads - intact, total_tails - intact
    return {
        "total_sperm": intact + max(tailless, headless),
        "intact": intact,
        "tailless": tailless,
        "headless": headless,
        "total_heads": total_heads,
        "total_tails": total_tails,
        "barely_visible": sum(i.tail_count for i in instances if i.kind == "barely_visible"),
    }


def analyze_image(gray: NDArray[Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or Settings()
    height, width = gray.shape
    scale = scale_factor(width, height, settings.magnification)
    masks = build_masks(gray, settings)
    sperm_pixels = masks["sperm_pixels"]

    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(sperm_pixels, connectivity=8)
    instance_map = np.zeros((height, width), dtype=np.uint16)
    instances: list[SpermInstance] = []
    min_tail = settings.min_tail_length * scale
    pad = 2
    for label_idx in range(1, n_labels):
        x, y, w, h, area = (int(v) for v in stats[label_idx])
        if max(w, h) < min_tail * 0.5:
            continue
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(width, x + w + pad), min(height, y + h + pad)
        component = (labels[y0:y1, x0:x1] == label_idx).astype(np.uint8) * 255
        mass = measure_tail_mass(component, settings, scale)
        if mass is None:
            continue
        skeleton = mass["skeleton"]

        candidates: list[HeadCandidate] = []
        accepted: list[HeadCandidate] = []
        merge_px = settings.head_merge_px * scale
        for core_px in (settings.head_core_px, settings.thin_head_core_px):
            pass_candidates = find_heads(
                component,
                skeleton,
                masks["blob"][y0:y1, x0:x1],
                masks["darkness"][y0:y1, x0:x1],
                settings,
                scale,
                core_px,
            )
            for cand in pass_candidates:
                cand.xy = [cand.xy[0] + x0, cand.xy[1] + y0]
            select_heads(pass_candidates, settings, strict=core_px != settings.head_core_px)
            for cand in pass_candidates:
                if not cand.accepted:
                    continue
                duplicate = any(
                    cand.dark_blob_id == other.dark_blob_id
                    or np.hypot(cand.xy[0] - other.xy[0], cand.xy[1] - other.xy[1]) <= merge_px
                    for other in accepted
                )
                if duplicate:
                    cand.accepted = False
                    cand.reason = "duplicate_of_other_pass"
                else:
                    accepted.append(cand)
            candidates.extend(pass_candidates)
        drop_faint_necks(accepted, settings)
        heads = [cand.xy for cand in accepted if cand.accepted]

        instance_id = len(instances) + 1
        instance_map[y0:y1, x0:x1][component > 0] = instance_id
        instances.append(
            SpermInstance(
                instance_id=instance_id,
                kind="",  # set below, once heads resting on tails are known
                head_count=len(heads),
                tail_count=count_tails(skeleton, mass["halfwidth"], settings, scale),
                bbox_xywh=[x, y, w, h],
                area_px=area,
                tail_length_px=round(mass["length"], 1),
                straightness=round(mass["straightness"], 3),
                local_straightness=round(mass["local_straightness"], 3),
                path_fraction=round(mass["path_fraction"], 3),
                heads_xy=[[round(hx, 1), round(hy, 1)] for hx, hy in heads],
                head_candidates=candidates,
            )
        )

    add_lens_heads(instances, instance_map, masks, settings, scale)
    for inst in instances:
        if inst.kind != "tailless":
            # Every accepted head has a tail reaching it, whatever the skeleton ends say.
            inst.tail_count = max(inst.tail_count, inst.head_count)
            inst.kind = classify_mass(inst.head_count, inst.tail_count)
    add_barely_visible(instances, instance_map, masks, settings, scale)

    return {
        "instances": instances,
        "instance_map": instance_map,
        "masks": masks,
        "counts": count_totals(instances),
        "magnification": settings.magnification,
    }


def draw_count_key(out: NDArray[Any], result: dict[str, Any]) -> None:
    """The counts and color key, on a darkened panel in the top-left corner."""
    counts = result["counts"]
    clusters = sum(1 for i in result["instances"] if i.kind == "overlap_cluster")
    white = (255, 255, 255)
    lines = [
        (f"Total sperm: {counts['total_sperm']}", white, None),
        (f"Intact: {counts['intact']}", INTACT_COLOR, INTACT_COLOR),
        (f"Tail-less: {counts['tailless']}", TAILLESS_COLOR, TAILLESS_COLOR),
        (f"Head-less: {counts['headless']}", HEADLESS_COLOR, HEADLESS_COLOR),
        (f"Overlap clusters: {clusters}", CLUSTER_COLOR, CLUSTER_COLOR),
        (f"Barely visible: {counts['barely_visible']}", BARELY_VISIBLE_COLOR, BARELY_VISIBLE_COLOR),
        (f"Total heads: {counts['total_heads']}", white, None),
        (f"Total tails: {counts['total_tails']}", white, None),
    ]
    line_height, width = 26, 320
    height = line_height * len(lines) + 12
    panel = out[:height, :width]
    panel[:] = (panel * 0.3).astype(np.uint8)
    for row, (text, color, swatch) in enumerate(lines):
        baseline = 25 + row * line_height
        if swatch is not None:
            cv2.rectangle(out, (10, baseline - 14), (24, baseline), swatch, -1)
        left = 32 if swatch is not None else 10
        cv2.putText(out, text, (left, baseline), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)


def render_overlay(gray: NDArray[Any], result: dict[str, Any]) -> NDArray[Any]:
    rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
    overlay = rgb.astype(np.float32)
    instance_map = result["instance_map"]
    colors = {
        "intact": INTACT_COLOR,
        "overlap_cluster": CLUSTER_COLOR,
        "headless": HEADLESS_COLOR,
        "tailless": TAILLESS_COLOR,
        "barely_visible": BARELY_VISIBLE_COLOR,
    }
    for inst in result["instances"]:
        region = instance_map == inst.instance_id
        region = cv2.dilate(region.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        overlay[region] = 0.35 * overlay[region] + 0.65 * np.array(colors[inst.kind], np.float32)
    out = overlay.astype(np.uint8)
    head_number = 0
    for inst in result["instances"]:
        x, y, _, _ = inst.bbox_xywh
        if inst.kind != "tailless":
            label = (
                f"#{inst.instance_id} {inst.head_count}H {inst.tail_count}T"
                if inst.kind == "overlap_cluster"
                else f"#{inst.instance_id}"
            )
            cv2.putText(
                out, label, (x, max(14, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colors[inst.kind], 2
            )
        marker = TAILLESS_COLOR if inst.kind == "tailless" else HEAD_COLOR
        for hx, hy in inst.heads_xy:
            head_number += 1
            center = (int(round(hx)), int(round(hy)))
            cv2.circle(out, center, 14, marker, 2)
            cv2.putText(
                out,
                str(head_number),
                (center[0] + 15, center[1] + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                marker,
                2,
            )
    draw_count_key(out, result)
    return out


def write_outputs(
    image_path: Path,
    gray: NDArray[Any],
    result: dict[str, Any],
    out_dir: Path,
    minimal: bool = False,
) -> dict[str, Any]:
    """Write per-image artifacts.

    minimal=True writes only original, overlay and candidate pixels.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    Image.fromarray(gray).save(out_dir / "original.png")
    Image.fromarray(render_overlay(gray, result)).save(out_dir / "overlay.png")
    Image.fromarray(result["masks"]["sperm_pixels"]).save(out_dir / "candidate_pixels.png")
    height, width = gray.shape
    if not minimal:
        Image.fromarray(((result["instance_map"] > 0) * 255).astype(np.uint8)).save(
            out_dir / "sperm_mask.png"
        )
        cv2.imwrite(str(out_dir / "instance_labels.png"), result["instance_map"])
        write_crops(gray, result, out_dir / "crops")

    summary = {
        "image": str(image_path),
        "width": width,
        "height": height,
        **result["counts"],
        "overlap_clusters": sum(1 for i in result["instances"] if i.kind == "overlap_cluster"),
        "magnification": result["magnification"],
        "noise_sigma": round(result["masks"]["noise"], 3),
        "ridge_low": round(result["masks"]["ridge_low"], 3),
        "ridge_high": round(result["masks"]["ridge_high"], 3),
    }
    if not minimal:
        with (out_dir / "instances.json").open("w") as handle:
            json.dump(
                {"summary": summary, "instances": [asdict(i) for i in result["instances"]]},
                handle,
                indent=2,
            )
    return summary


def write_crops(gray: NDArray[Any], result: dict[str, Any], crops_dir: Path) -> None:
    crops_dir.mkdir(exist_ok=True)
    rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
    height, width = gray.shape
    for inst in result["instances"]:
        x, y, w, h = inst.bbox_xywh
        margin = 12
        x0, y0 = max(0, x - margin), max(0, y - margin)
        x1, y1 = min(width, x + w + margin), min(height, y + h + margin)
        crop = rgb[y0:y1, x0:x1].copy()
        region = result["instance_map"][y0:y1, x0:x1] == inst.instance_id
        crop[region] = (0.5 * crop[region] + 0.5 * np.array(INTACT_COLOR)).astype(np.uint8)
        Image.fromarray(crop).save(crops_dir / f"{inst.instance_id:03d}_{inst.kind}.png")


def batch_stats_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Total, mean, median, and range across images, one row per count column."""
    stats = []
    for column in COUNT_COLUMNS:
        values = [row[column] for row in rows]
        stats.append(
            {
                "count": column,
                "total": sum(values),
                "mean": round(statistics.mean(values), 3),
                "median": statistics.median(values),
                "min": min(values),
                "max": max(values),
            }
        )
    return stats


def collect_images(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    return sorted(
        p
        for p in input_path.rglob("*")
        if p.suffix.lower() in IMAGE_EXTS
        and not p.name.startswith("._")
        and "__MACOSX" not in p.parts
        and "outputs" not in p.relative_to(input_path).parts
    )


def settings_for_magnification(magnification: float) -> Settings:
    """Settings for a given objective magnification.

    Lengths scale with magnification / REFERENCE_MAGNIFICATION. From 40x up the
    images show relief contrast (hollow outlined heads), so the blob mask
    switches to either-sign contrast with hole filling. The 40x preset is
    experimental: it has not been validated against manual counts.
    """
    if magnification <= 0:
        raise ValueError("magnification must be positive")
    return Settings(magnification=magnification, relief_contrast=magnification >= 40)


def magnification_from_name(name: str) -> float | None:
    match = re.search(r"(?:^|_)(\d+(?:\.\d+)?)x(?:_|$)", Path(name).stem, flags=re.IGNORECASE)
    return float(match.group(1)) if match else None


def version_text() -> str:
    """'eyespysc <version>', plus the source commit in packaged builds."""
    text = f"eyespysc {__version__}"
    if BUILD_REVISION_FILE.is_file():
        text += f" (build {BUILD_REVISION_FILE.read_text(encoding='utf-8').strip()})"
    return text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="eyespysc", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--version", action="version", version=version_text())
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        action="append",
        help="Image file, or folder searched recursively for images "
        "(.tif .tiff .png .jpg .jpeg .bmp). Repeat for several.",
    )
    parser.add_argument(
        "--output-root", type=Path, required=True, help="Folder to create for the results."
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="Delete and recreate --output-root first."
    )
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="Per image, write only original.png, overlay.png and candidate_pixels.png.",
    )
    parser.add_argument(
        "--magnification",
        type=float,
        default=REFERENCE_MAGNIFICATION,
        help=f"Objective magnification of the inputs (default {REFERENCE_MAGNIFICATION:g}, "
        "the magnification the settings were tuned on).",
    )
    parser.add_argument(
        "--magnification-from-filename",
        action="store_true",
        help="Use a '_<N>x_' token in a file name (e.g. caput_40x_0019) when present, "
        "otherwise --magnification.",
    )
    parser.add_argument(
        "--preview-only",
        action="store_true",
        help="Do not count. Write an 8-bit preview.png and thumb.png per image "
        "(for the desktop app).",
    )
    parser.add_argument(
        "--json-progress",
        action="store_true",
        help="Print one JSON object per line (start, image, done) instead of text.",
    )
    return parser.parse_args()


def plan_outputs(inputs: list[Path], output_root: Path) -> list[tuple[Path, Path, str]]:
    """(image, output folder, display name) for every image under the inputs."""
    planned = []
    owners: dict[Path, Path] = {}
    for input_path in inputs:
        input_root = input_path if input_path.is_dir() else input_path.parent
        for image_path in collect_images(input_path):
            relative = image_path.relative_to(input_root)
            # Mirror input subfolders: the same file name recurs across sessions.
            out_dir = output_root / relative.parent / image_path.stem
            if out_dir in owners:
                raise SystemExit(
                    f"{owners[out_dir]} and {image_path} would both write to {out_dir}; "
                    "count them separately."
                )
            owners[out_dir] = image_path
            planned.append((image_path, out_dir, str(relative)))
    return planned


def write_preview(gray: NDArray[Any], path: Path, long_side: int = PREVIEW_LONG_SIDE) -> None:
    height, width = gray.shape
    scale = long_side / max(height, width)
    if scale < 1:
        size = (round(width * scale), round(height * scale))
        gray = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(gray).save(path)


def emit(event: dict[str, Any]) -> None:
    # NumPy scalars in the summary are not JSON types; .item() converts them.
    print(json.dumps(event, default=lambda value: value.item()), flush=True)


def main() -> None:
    args = parse_args()
    output_root = args.output_root
    if output_root.exists():
        if not args.overwrite:
            raise SystemExit(f"{output_root} exists; pass --overwrite to replace it.")
        shutil.rmtree(output_root)
    planned = plan_outputs(args.input, output_root)
    if not planned:
        raise SystemExit(f"No images found under {', '.join(str(p) for p in args.input)}")

    total = len(planned)
    if args.json_progress:
        emit({"event": "start", "total": total, "preview_only": args.preview_only})
    rows = []
    for index, (image_path, out_dir, name) in enumerate(planned, start=1):
        gray = load_gray(image_path)
        image_event: dict[str, Any] = {
            "event": "image",
            "index": index,
            "total": total,
            "name": name,
            "image": str(image_path.resolve()),
        }
        if args.preview_only:
            write_preview(gray, out_dir / "preview.png")
            write_preview(gray, out_dir / "thumb.png", THUMB_LONG_SIDE)
            if args.json_progress:
                height, width = gray.shape
                folder = out_dir.resolve()
                emit(
                    {
                        **image_event,
                        "preview": str(folder / "preview.png"),
                        "thumb": str(folder / "thumb.png"),
                        "width": width,
                        "height": height,
                    }
                )
            else:
                print(f"{name}: preview written")
            continue

        magnification = args.magnification
        if args.magnification_from_filename:
            magnification = magnification_from_name(image_path.name) or magnification
        result = analyze_image(gray, settings_for_magnification(magnification))
        summary = write_outputs(image_path, gray, result, out_dir, minimal=args.minimal)
        rows.append(summary)
        if args.json_progress:
            folder = out_dir.resolve()
            emit(
                {
                    **image_event,
                    "output_dir": str(folder),
                    "original": str(folder / "original.png"),
                    "overlay": str(folder / "overlay.png"),
                    "summary": summary,
                }
            )
        else:
            print(
                f"{name}: {summary['total_sperm']} sperm "
                f"({summary['intact']} intact, {summary['tailless']} tail-less, "
                f"{summary['headless']} head-less; "
                f"{summary['total_heads']} heads, {summary['total_tails']} tails; "
                f"{summary['barely_visible']} barely visible)"
            )

    if args.preview_only:
        if args.json_progress:
            emit({"event": "done", "total": total})
        return
    summary_csv = output_root / "summary.csv"
    with summary_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    stats_csv = output_root / "batch_stats.csv"
    stats_rows = batch_stats_rows(rows)
    with stats_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(stats_rows[0].keys()))
        writer.writeheader()
        writer.writerows(stats_rows)
    if args.json_progress:
        emit(
            {
                "event": "done",
                "total": total,
                "output_root": str(output_root.resolve()),
                "summary_csv": str(summary_csv.resolve()),
                "batch_stats_csv": str(stats_csv.resolve()),
            }
        )
