# Releasing EyeSpySC

Human runbook. Follows `/home/kyle/Desktop/Adam/SOFTWARE_RELEASE_STANDARD.md`
section 9. Releases are built only by GitHub Actions
(`.github/workflows/release-linux.yml`) from an annotated tag on a commit that
already passed CI. Never upload a locally built package.

```bash
# 0. Access
git remote -v && gh auth status && ssh -T git@github.com

# 1. Test
./scripts/check.sh
# Regression: must equal outputs/runFull_2026-11-02/summary.csv unless counts are meant to change
backend/.venv/bin/eyespysc --input inputsTest --output-root <scratch dir> \
  --minimal --magnification-from-filename

# Optional local packaging dry run (needs backend[packaging], Node 22, Rust 1.98)
scripts/build-linux-sidecars.sh
scripts/smoke-packaged-cli.sh backend/dist/sidecars/eyespysc-cli-x86_64-unknown-linux-gnu \
  "$(git rev-parse HEAD)"
(cd desktop && npm run tauri:release)   # deb under desktop/src-tauri/target/.../bundle/deb
# Manual GUI check: choose a folder, browse, Count sperm, browse overlays
# Or run the release build job on GitHub without publishing:
gh workflow run release-linux.yml --ref main

# 2. Pick the version
git fetch origin --tags
git tag --list 'v*' --sort=-v:refname | head
./scripts/update-release-version.sh v0.1.0-rc.1

# 3. Commit and push. Stage files explicitly; review before committing
git status --short
git add <files>
git diff --cached --check
git commit -m "EyeSpySC v0.1.0-rc.1: <short title>"
git push origin main
gh run list --branch main --limit 3      # wait for CI on this exact commit

# 4. Tag the exact commit CI approved
git tag -a v0.1.0-rc.1 <commit-sha> -m "EyeSpySC v0.1.0-rc.1: <short title>"
git push origin v0.1.0-rc.1
gh run watch                             # release workflow
gh release view v0.1.0-rc.1
```

The release is one ZIP, `EyeSpySC_ver<version>_Linux-x86_64_Ubuntu-Debian.zip`,
containing `eyespysc_<version>_linux-x86_64.deb`, `SHA256SUMS`, and
`installation.md`. Versions containing `-` are published as prereleases.

| Situation | Tag |
|---|---|
| Not yet verified by a clean-machine install | `vX.Y.Z-rc.N` |
| An rc passed the clean-machine check (standard section 10) | `vX.Y.Z`, same code |
| A bug found after a stable release | `vX.Y.(Z+1)` |

A failed tag stays bound to its commit. Never delete, move, or reuse it; fix
the problem and cut the next rc.
