# Third-party notices

EyeSpySC is MIT-licensed (see `LICENSE`). The release package contains two
programs: the desktop app, `/usr/bin/eyespysc-desktop`, and the counting
command, `/usr/bin/eyespysc`.

## Counting command (`/usr/bin/eyespysc`)

A single PyInstaller executable that bundles a Python 3.11 runtime and these
Python packages, at the exact versions pinned in
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

## Desktop app (`/usr/bin/eyespysc-desktop`)

A Tauri 2 application. The Rust binary statically links Tauri and its crate
dependencies (versions in `desktop/src-tauri/Cargo.lock`, mostly MIT or
Apache-2.0 dual-licensed). The bundled web interface includes React and
React DOM 18.3.1 (MIT) and the Tauri JavaScript API and dialog plugin
(MIT or Apache-2.0), at the versions in `desktop/package-lock.json`. The app
uses the system WebKitGTK and GTK libraries (LGPL), which `apt` installs as
package dependencies; they are not bundled. The house-style CSS and the
title-bar and folder-opener code are adapted from Missus Tom, a Yan Lab project
(MIT).

The app icon and logo are the developer's own artwork.

## Other

`scp_helpers.py` is copied from Sperm Color Pixels
(github.com/Bioticcc/SCP-SpermColorPixels), a Yan Lab project; its header
records the source commit.

EyeSpySC downloads nothing at install or run time. Release artifacts contain no
microscope images, counts, annotations, generated outputs, logs, credentials,
or runtime state.
