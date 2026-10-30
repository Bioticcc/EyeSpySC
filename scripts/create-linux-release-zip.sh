#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --version VERSION --deb PACKAGE.deb --output-dir DIRECTORY" >&2
  exit 2
}

release_version=""
deb_source=""
output_directory=""

while (( $# > 0 )); do
  case "$1" in
    --version)
      (( $# >= 2 )) || usage
      release_version="$2"
      shift 2
      ;;
    --deb)
      (( $# >= 2 )) || usage
      deb_source="$2"
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

[[ -n "${release_version}" && -n "${deb_source}" && -n "${output_directory}" ]] || usage

if [[ ! "${release_version}" =~ ^[0-9][0-9A-Za-z.+-]*$ ]]; then
  echo "Release version must start with a digit and contain only letters, digits, '.', '+', or '-'." >&2
  exit 2
fi
if [[ ! -f "${deb_source}" ]]; then
  echo "Debian package does not exist or is not a regular file: ${deb_source}" >&2
  exit 2
fi

mkdir -p "${output_directory}"
if [[ ! -d "${output_directory}" ]]; then
  echo "Release output path is not a directory: ${output_directory}" >&2
  exit 2
fi
output_directory="$(cd "${output_directory}" && pwd -P)"

zip_name="EyeSpySC_ver${release_version}_Linux-x86_64_Ubuntu-Debian.zip"
zip_path="${output_directory}/${zip_name}"
if [[ -e "${zip_path}" ]] || find "${output_directory}" -maxdepth 1 -type f -name '*.zip' -print -quit | grep -q .; then
  echo "Release output directory must not already contain a ZIP: ${output_directory}" >&2
  exit 2
fi

staging_directory="$(mktemp -d)"
trap 'rm -rf "${staging_directory}"' EXIT
deb_name="eyespysc_${release_version}_linux-x86_64.deb"

install -m 0644 "${deb_source}" "${staging_directory}/${deb_name}"
(
  cd "${staging_directory}"
  sha256sum "${deb_name}" >SHA256SUMS
  cat >installation.md <<EOF
# Install EyeSpySC on Ubuntu or Debian

Run every command from the folder this file was unzipped into. For example,
if the ZIP is in ~/Downloads:

   \`\`\`bash
   cd ~/Downloads
   unzip EyeSpySC_ver${release_version}_Linux-x86_64_Ubuntu-Debian.zip -d EyeSpySC_ver${release_version}
   cd EyeSpySC_ver${release_version}
   \`\`\`

1. Verify the installer checksum. It should print \`${deb_name}: OK\`:

   \`\`\`bash
   sha256sum --check SHA256SUMS
   \`\`\`

2. Install the verified package. Keep the leading \`./\`; without it apt
   looks for the package online:

   \`\`\`bash
   sudo apt install ./${deb_name}
   \`\`\`

3. Open **EyeSpySC** from the applications menu, or run:

   \`\`\`bash
   eyespysc-desktop
   \`\`\`

   Choose a folder or images, look through them, then press **Count sperm**.
   Accepted files: .tif, .tiff, .png, .jpg, .jpeg and .bmp, 8- or 16-bit
   grayscale (color is converted to gray).
   Results are saved under \`~/EyeSpySC results/\` and shown in the app.

4. Or count from a terminal:

   \`\`\`bash
   eyespysc --input /path/to/images --output-root /path/to/results
   \`\`\`

   The output folder must not exist yet (\`--overwrite\` replaces it).
   Results: \`summary.csv\` plus one folder of overlays per image. Run
   \`eyespysc --help\` for all options.

Settings are tuned for 20x grayscale phase-contrast images only, and counts
are provisional until validated against expert counts. On WSL the app opens
through WSLg.

To uninstall: \`sudo apt remove eyespysc\`.
EOF
  zip -q "${zip_path}" "${deb_name}" SHA256SUMS installation.md
)
