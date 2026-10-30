"""Deterministic sperm highlighting and counting for low-contrast grayscale images.

EyeSpySC is an offshoot of Sperm Color Pixels (SCP). It reuses SCP's
local-background darkness idea and skeleton helpers, but replaces the brown
stain color gate (which needs RGB Ward images) with a multi-scale Hessian ridge
filter that finds faint thin dark tails in grayscale phase-contrast images.

Inputs are assumed to contain little or no tail overlap. When one connected
sperm mass contains more than one head, the whole mass is highlighted as an
overlap cluster and its heads are counted individually.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
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

SINGLE_COLOR = (0, 220, 90)
CLUSTER_COLOR = (255, 140, 0)
HEADLESS_COLOR = (0, 170, 255)
HEAD_COLOR = (255, 40, 40)


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
    min_tail_branch: float = 40.0  # length of the skeleton network a head's tail joins
    min_tail_segment: float = 12.0  # first segment leaving the head, before any junction
    min_branch_straightness: float = 0.5
    neck_length: float = 30.0
    # Only used to break ties inside a multi-head mass: a candidate whose neck is
    # both faint in absolute terms and much fainter than the darkest neck in the
    # same mass is treated as debris on a tail end, not a second head.
    faint_neck_darkness: float = 5.0
    faint_neck_ratio: float = 0.5
    prune_iterations: int = 3


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
    kind: str  # "single" | "overlap_cluster" | "headless_tail"
    head_count: int
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
        skeleton = prune_skeleton_endpoints(
            skeletonize(component), max(1, int(round(settings.prune_iterations * scale)))
        )
        if not np.any(skeleton):
            continue
        path = longest_skeleton_path(skeleton)
        length = path_length(path)
        if length < min_tail:
            continue
        chord = float(np.linalg.norm((path[0] - path[-1]).astype(np.float32)))
        straightness = chord / max(length, 1.0)
        local = local_straightness(path, settings.straightness_window * scale)
        path_fraction = len(path) / max(1, int(np.count_nonzero(skeleton)))
        halfwidth = cv2.distanceTransform((component > 0).astype(np.uint8), cv2.DIST_L2, 3)
        thin_length = float(
            np.count_nonzero(
                halfwidth[path[:, 0], path[:, 1]] <= settings.max_tail_halfwidth * scale
            )
        )
        if thin_length < min_tail or local < settings.min_local_straightness:
            continue

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
        if len(heads) == 0:
            kind = "headless_tail"
        elif len(heads) == 1:
            kind = "single"
        else:
            kind = "overlap_cluster"

        instance_id = len(instances) + 1
        instance_map[y0:y1, x0:x1][component > 0] = instance_id
        instances.append(
            SpermInstance(
                instance_id=instance_id,
                kind=kind,
                head_count=len(heads),
                bbox_xywh=[x, y, w, h],
                area_px=area,
                tail_length_px=round(length, 1),
                straightness=round(straightness, 3),
                local_straightness=round(local, 3),
                path_fraction=round(path_fraction, 3),
                heads_xy=[[round(hx, 1), round(hy, 1)] for hx, hy in heads],
                head_candidates=candidates,
            )
        )

    return {
        "instances": instances,
        "instance_map": instance_map,
        "masks": masks,
        "sperm_count": sum(inst.head_count for inst in instances),
        "magnification": settings.magnification,
    }


def render_overlay(gray: NDArray[Any], result: dict[str, Any]) -> NDArray[Any]:
    rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
    overlay = rgb.astype(np.float32)
    instance_map = result["instance_map"]
    colors = {
        "single": SINGLE_COLOR,
        "overlap_cluster": CLUSTER_COLOR,
        "headless_tail": HEADLESS_COLOR,
    }
    for inst in result["instances"]:
        region = instance_map == inst.instance_id
        region = cv2.dilate(region.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        overlay[region] = 0.35 * overlay[region] + 0.65 * np.array(colors[inst.kind], np.float32)
    out = overlay.astype(np.uint8)
    head_number = 0
    for inst in result["instances"]:
        x, y, _, _ = inst.bbox_xywh
        label = (
            f"#{inst.instance_id}"
            if inst.kind == "headless_tail"
            else f"#{inst.instance_id} x{inst.head_count}"
        )
        cv2.putText(
            out, label, (x, max(14, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colors[inst.kind], 2
        )
        for hx, hy in inst.heads_xy:
            head_number += 1
            center = (int(round(hx)), int(round(hy)))
            cv2.circle(out, center, 14, HEAD_COLOR, 2)
            cv2.putText(
                out,
                str(head_number),
                (center[0] + 15, center[1] + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                HEAD_COLOR,
                2,
            )
    banner = f"sperm count (heads): {result['sperm_count']}"
    cv2.putText(out, banner, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 4)
    cv2.putText(out, banner, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
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

    counts = {
        kind: sum(1 for i in result["instances"] if i.kind == kind)
        for kind in ("single", "overlap_cluster", "headless_tail")
    }
    summary = {
        "image": str(image_path),
        "width": width,
        "height": height,
        "sperm_count": result["sperm_count"],
        "single_instances": counts["single"],
        "overlap_clusters": counts["overlap_cluster"],
        "heads_in_overlap_clusters": sum(
            i.head_count for i in result["instances"] if i.kind == "overlap_cluster"
        ),
        "headless_tail_segments": counts["headless_tail"],
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
        crop[region] = (0.5 * crop[region] + 0.5 * np.array(SINGLE_COLOR)).astype(np.uint8)
        Image.fromarray(crop).save(crops_dir / f"{inst.instance_id:03d}_{inst.kind}.png")


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
        help="Image file, or folder searched recursively for images.",
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_root = args.output_root
    if output_root.exists():
        if not args.overwrite:
            raise SystemExit(f"{output_root} exists; pass --overwrite to replace it.")
        shutil.rmtree(output_root)
    images = collect_images(args.input)
    if not images:
        raise SystemExit(f"No images found under {args.input}")

    input_root = args.input if args.input.is_dir() else args.input.parent
    rows = []
    for image_path in images:
        gray = load_gray(image_path)
        magnification = args.magnification
        if args.magnification_from_filename:
            magnification = magnification_from_name(image_path.name) or magnification
        result = analyze_image(gray, settings_for_magnification(magnification))
        # Mirror input subfolders: the same file name recurs across sessions.
        out_dir = output_root / image_path.relative_to(input_root).parent / image_path.stem
        summary = write_outputs(image_path, gray, result, out_dir, minimal=args.minimal)
        rows.append(summary)
        print(
            f"{image_path.relative_to(input_root)}: {summary['sperm_count']} sperm "
            f"({summary['single_instances']} single, "
            f"{summary['overlap_clusters']} overlap clusters, "
            f"{summary['headless_tail_segments']} headless tail segments)"
        )

    with (output_root / "summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
