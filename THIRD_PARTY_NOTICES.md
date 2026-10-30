# Third-party notices

EyeSpySC is MIT-licensed (see `LICENSE`). The release package contains a
single PyInstaller executable, `/usr/bin/eyespysc`, that bundles a Python 3.11
runtime and these Python packages, at the exact versions pinned in
`backend/requirements-build.lock`:

| Component | Version | License (as declared upstream) |
|---|---|---|
| CPython runtime | 3.11 | Python Software Foundation License |
| NumPy | 2.2.6 | BSD-3-Clause |
| opencv-python-headless | 4.13.0.92 | Apache-2.0 |
| Pillow | 12.2.0 | MIT-CMU |
| PyInstaller bootloader | 6.11.1 | GPL-2.0-or-later with the PyInstaller bootloader exception, which permits distributing bundled programs |

These wheels also ship native libraries with their own licenses: OpenBLAS and
the GCC Fortran runtime (NumPy and OpenCV); FFmpeg, libaom, libvpx, libpng and
OpenSSL (OpenCV); and libjpeg-turbo, libtiff, libwebp, libavif, libpng,
FreeType, HarfBuzz, Little CMS, OpenJPEG, xz, zstd, Brotli, libxcb and libXau
(Pillow). Their license texts are distributed in each upstream wheel
(`*.dist-info/` license files; OpenCV's `LICENSE-3RD-PARTY.txt`). The terms
that apply are those supplied by the upstream projects. This document does not
assign a license where upstream terms have not been independently reviewed.

`scp_helpers.py` is copied from Sperm Color Pixels
(github.com/Bioticcc/SCP-SpermColorPixels), a Yan Lab project; its header
records the source commit.

EyeSpySC downloads nothing at install or run time. Release artifacts contain no
microscope images, counts, annotations, generated outputs, logs, credentials,
or runtime state.
