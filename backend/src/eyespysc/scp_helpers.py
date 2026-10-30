"""Skeleton and mask helpers copied from Sperm Color Pixels (SCP).

Source: github.com/Bioticcc/SCP-SpermColorPixels
        Algorithmic_Pixel_Mask_For_Tails/algorithmic_tail_mask.py
        commit 5217d2f12b80d0f52cbad4eda8fd07b3c4cc30d5, copied 2026-10-30.

The function bodies are copied unchanged. Do not edit them here without
recording the change: validated counts depend on their exact behavior.

skeletonize_binary uses cv2.ximgproc.thinning when OpenCV-contrib is installed,
and Zhang-Suen otherwise. All validated counts so far used Zhang-Suen (plain
opencv-python, no ximgproc).
"""

from __future__ import annotations

import cv2
import numpy as np


def remove_small_components(mask: np.ndarray, min_area: int) -> np.ndarray:
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    cleaned = np.zeros(mask.shape, dtype=np.uint8)
    for label_idx in range(1, n_labels):
        area = int(stats[label_idx, cv2.CC_STAT_AREA])
        if area >= min_area:
            cleaned[labels == label_idx] = 255
    return cleaned


def skeletonize_binary(mask: np.ndarray) -> np.ndarray:
    mask = (mask > 0).astype(np.uint8) * 255
    if not np.any(mask):
        return mask

    if hasattr(cv2, "ximgproc") and hasattr(cv2.ximgproc, "thinning"):
        return cv2.ximgproc.thinning(mask)

    return zhang_suen_thinning(mask)


def zhang_suen_thinning(mask: np.ndarray) -> np.ndarray:
    img = (mask > 0).astype(np.uint8)
    if not np.any(img):
        return img * 255

    img = np.pad(img, 1, mode="constant")
    changed = True
    while changed:
        changed = False
        for step in (0, 1):
            p2 = img[:-2, 1:-1]
            p3 = img[:-2, 2:]
            p4 = img[1:-1, 2:]
            p5 = img[2:, 2:]
            p6 = img[2:, 1:-1]
            p7 = img[2:, :-2]
            p8 = img[1:-1, :-2]
            p9 = img[:-2, :-2]
            center = img[1:-1, 1:-1]

            neighbors = [p2, p3, p4, p5, p6, p7, p8, p9]
            neighbor_count = sum(neighbors)
            transitions = sum(
                (neighbors[idx] == 0) & (neighbors[(idx + 1) % 8] == 1)
                for idx in range(8)
            )

            if step == 0:
                cond_a = (p2 * p4 * p6) == 0
                cond_b = (p4 * p6 * p8) == 0
            else:
                cond_a = (p2 * p4 * p8) == 0
                cond_b = (p2 * p6 * p8) == 0

            remove = (
                (center == 1)
                & (neighbor_count >= 2)
                & (neighbor_count <= 6)
                & (transitions == 1)
                & cond_a
                & cond_b
            )
            if np.any(remove):
                center[remove] = 0
                changed = True

    return (img[1:-1, 1:-1] * 255).astype(np.uint8)


def prune_skeleton_endpoints(skeleton: np.ndarray, iterations: int) -> np.ndarray:
    pruned = (skeleton > 0).astype(np.uint8)
    kernel = np.ones((3, 3), dtype=np.uint8)
    for _ in range(max(0, iterations)):
        if not np.any(pruned):
            break
        neighbor_count = cv2.filter2D(pruned, cv2.CV_16S, kernel, borderType=cv2.BORDER_CONSTANT) - pruned
        endpoints = (pruned > 0) & (neighbor_count <= 1)
        if not np.any(endpoints):
            break
        pruned[endpoints] = 0
    return pruned.astype(np.uint8) * 255
