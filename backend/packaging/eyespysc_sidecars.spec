"""Build the Linux eyespysc command-line sidecar."""

from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.building.build_main import EXE, PYZ, Analysis

target = os.environ["EYESPYSC_SIDECAR_TARGET"]
resource_stage = Path(os.environ["EYESPYSC_SIDECAR_RESOURCE_STAGE"])
if not resource_stage.is_dir():
    raise SystemExit(f"Resource staging directory is missing: {resource_stage}")

backend_root = Path(SPECPATH).resolve().parent  # noqa: F821 (defined by PyInstaller)

analysis = Analysis(
    [str(backend_root / "packaging" / "eyespysc_entry.py")],
    pathex=[str(backend_root / "src")],
    binaries=[],
    # build_revision.txt lands next to the frozen eyespysc modules, where
    # sperm_count.BUILD_REVISION_FILE looks for it.
    datas=[(str(resource_stage / "build_revision.txt"), "eyespysc")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Never bundle contrib thinning or GUI toolkits.
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    name=f"eyespysc-cli-{target}",
    console=True,
)
