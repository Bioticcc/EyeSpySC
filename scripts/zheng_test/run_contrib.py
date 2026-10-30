"""Run the eyespysc CLI with SCP's original skeletonize_binary.

skeletonize_binary uses cv2.ximgproc.thinning when OpenCV-contrib is installed,
which the shipped pipeline deliberately bypasses. Arguments pass through to the
eyespysc command line.
"""

import sys

import cv2

from eyespysc import scp_helpers
from eyespysc import sperm_count as sc

if not (hasattr(cv2, "ximgproc") and hasattr(cv2.ximgproc, "thinning")):
    raise SystemExit("OpenCV-contrib (cv2.ximgproc.thinning) is not installed.")

calls = 0
contrib_thinning = cv2.ximgproc.thinning


def counting_thinning(*args, **kwargs):
    global calls
    calls += 1
    return contrib_thinning(*args, **kwargs)


cv2.ximgproc.thinning = counting_thinning
sc.skeletonize = scp_helpers.skeletonize_binary
sc.main()
if calls == 0:
    raise SystemExit("cv2.ximgproc.thinning was never called.")
print(f"cv2.ximgproc.thinning calls: {calls}", file=sys.stderr)
