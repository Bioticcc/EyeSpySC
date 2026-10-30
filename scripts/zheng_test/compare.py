"""Compare the numpy Zhang-Suen and OpenCV-contrib runs of the ZhengTest.

Writes comparison.csv and side_by_side/<image>/ with the raw image, both
overlays, an overlay-difference mask, and a zoomed crop for every instance
whose head positions differ.
"""

import csv
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from eyespysc.sperm_count import collect_images, load_gray

root, input_root = Path(sys.argv[1]), Path(sys.argv[2])
numpy_dir, contrib_dir = root / "zhang_suen_numpy", root / "ximgproc_contrib"
side = root / "side_by_side"


def read_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def zoom(raw: np.ndarray, overlays: list[np.ndarray], bbox: list[int]) -> np.ndarray:
    x, y, w, h = bbox
    height, width = raw.shape[:2]
    x0, y0 = max(0, x - 60), max(0, y - 60)
    x1, y1 = min(width, x + w + 60), min(height, y + h + 60)
    panels = []
    for label, image in zip(
        ("raw", "zhang_suen_numpy", "ximgproc_contrib"), [raw, *overlays], strict=True
    ):
        panel = np.ascontiguousarray(
            cv2.resize(image[y0:y1, x0:x1], None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        )
        cv2.putText(panel, label, (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)
        panels.append(panel)
    bar = np.full((12, panels[0].shape[1], 3), 255, np.uint8)
    return np.vstack([panels[0], bar, panels[1], bar, panels[2]])


rows = []
input_dir = input_root if input_root.is_dir() else input_root.parent
for raw_path in collect_images(input_root):
    relative = raw_path.relative_to(input_dir).parent / raw_path.stem
    a, b = numpy_dir / relative, contrib_dir / relative
    ia = json.loads((a / "instances.json").read_text())["instances"]
    ib = json.loads((b / "instances.json").read_text())["instances"]
    la = cv2.imread(str(a / "instance_labels.png"), cv2.IMREAD_UNCHANGED)
    lb = cv2.imread(str(b / "instance_labels.png"), cv2.IMREAD_UNCHANGED)
    oa, ob = read_rgb(a / "overlay.png"), read_rgb(b / "overlay.png")
    overlay_diff = np.any(oa != ob, axis=2)
    same_instances = len(ia) == len(ib)
    moved = (
        [x for x, y in zip(ia, ib, strict=True) if x["heads_xy"] != y["heads_xy"]]
        if same_instances
        else []
    )
    rows.append(
        {
            "image": str(raw_path.relative_to(input_dir)),
            "count_zhang_suen_numpy": sum(i["head_count"] for i in ia),
            "count_ximgproc_contrib": sum(i["head_count"] for i in ib),
            "instances_numpy": len(ia),
            "instances_contrib": len(ib),
            "instance_label_pixels_differing": int(np.count_nonzero(la != lb)),
            "overlay_pixels_differing": int(np.count_nonzero(overlay_diff)),
            "instances_with_moved_heads": len(moved)
            if same_instances
            else "instance count differs",
            "max_tail_length_change_px": round(
                max(
                    (
                        abs(x["tail_length_px"] - y["tail_length_px"])
                        for x, y in zip(ia, ib, strict=True)
                    ),
                    default=0.0,
                ),
                1,
            )
            if same_instances
            else "instance count differs",
            "instances_json_identical": ia == ib,
        }
    )

    out = side / relative
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(raw_path, out / f"1_raw{raw_path.suffix}")
    shutil.copy(a / "overlay.png", out / "2_overlay_zhang_suen_numpy.png")
    shutil.copy(b / "overlay.png", out / "3_overlay_ximgproc_contrib.png")
    Image.fromarray((overlay_diff * 255).astype(np.uint8)).save(out / "4_overlay_difference.png")
    raw_rgb = cv2.cvtColor(load_gray(raw_path), cv2.COLOR_GRAY2RGB)
    for inst in moved:
        Image.fromarray(zoom(raw_rgb, [oa, ob], inst["bbox_xywh"])).save(
            out / f"5_zoom_instance{inst['instance_id']}_raw_numpy_contrib.png"
        )

with (root / "comparison.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
changed = [r for r in rows if r["count_zhang_suen_numpy"] != r["count_ximgproc_contrib"]]
moved_total = sum(
    r["instances_with_moved_heads"]
    for r in rows
    if isinstance(r["instances_with_moved_heads"], int)
)
print(
    f"{len(rows)} images; {len(changed)} with different counts; "
    f"{moved_total} instances with moved heads. See {root / 'comparison.csv'}."
)
