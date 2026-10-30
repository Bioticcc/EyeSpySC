#!/usr/bin/env bash
set -euo pipefail

# Build the CLI-only Debian package around the frozen eyespysc sidecar. The
# Tauri GUI will replace this with a Tauri deb bundle; the command stays
# /usr/bin/eyespysc.

usage() {
  echo "Usage: $0 --version SEMVER --cli PACKAGED-CLI --output-dir DIRECTORY" >&2
  exit 2
}

release_version=""
cli=""
output_directory=""

while (( $# > 0 )); do
  case "$1" in
    --version)
      (( $# >= 2 )) || usage
      release_version="$2"
      shift 2
      ;;
    --cli)
      (( $# >= 2 )) || usage
      cli="$2"
      shift 2
      ;;
    --output-dir)
      (( $# >= 2 )) || usage
      output_directory="$2"
      shift 2
      ;;
    *)
      usage
      ;;
  esac
done

[[ -n "${release_version}" && -n "${cli}" && -n "${output_directory}" ]] || usage
if [[ ! -x "${cli}" ]]; then
  echo "Packaged CLI is not executable: ${cli}" >&2
  exit 2
fi

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
staging_directory="$(mktemp -d)"
trap 'rm -rf "${staging_directory}"' EXIT
package="${staging_directory}/package"

install -D -m 0755 "${cli}" "${package}/usr/bin/eyespysc"
install -D -m 0644 "${repository_root}/LICENSE" "${package}/usr/share/doc/eyespysc/copyright"
install -D -m 0644 "${repository_root}/README.md" "${package}/usr/share/doc/eyespysc/README.md"
install -D -m 0644 "${repository_root}/THIRD_PARTY_NOTICES.md" \
  "${package}/usr/share/doc/eyespysc/THIRD_PARTY_NOTICES.md"

installed_size=$(du -sk "${package}/usr" | cut -f1)
mkdir -p "${package}/DEBIAN"
cat >"${package}/DEBIAN/control" <<CONTROL
Package: eyespysc
Version: ${release_version}
Architecture: amd64
Maintainer: Yan Lab <adamward.bio@gmail.com>
Installed-Size: ${installed_size}
Depends: libc6 (>= 2.35)
Section: science
Priority: optional
Homepage: https://github.com/Bioticcc/EyeSpySC
Description: Sperm counting for 20x grayscale phase-contrast images
 EyeSpySC highlights and counts sperm in low-contrast grayscale 20x
 phase-contrast microscope images using deterministic image processing.
 This package provides the eyespysc command-line tool.
CONTROL

mkdir -p "${output_directory}"
deb_path="${output_directory}/eyespysc_${release_version}_amd64.deb"
dpkg-deb --build --root-owner-group "${package}" "${deb_path}" >/dev/null
bash "${repository_root}/scripts/normalize-debian-release-version.sh" \
  --release-version "${release_version}" \
  --deb "${deb_path}" >&2
echo "${deb_path}"
