# Release maintenance

The default branch is `main`. Release tags are `vMAJOR.MINOR.PATCH`, matching
`cartridge.json` exactly. The app ID is fixed at `dev.cartridge.frequency` and this
release line requires `min_runtime: "0.6.2"`. Update the manifest version and
release notes, review `package-files.json`, and run the README checks before
committing and pushing a new tag.

```sh
python3 tools/package.py --tag v1.2.0
(cd dist && shasum -a 256 -c SHA256SUMS)
```

The stdlib packager rejects malformed manifests, mismatched tags, unsafe names,
missing modules/assets, symlinks, hard links, special files, and development
files in the payload. It sorts archive entries and normalizes owners, modes,
timestamps, and gzip headers. Identical input bytes with the same Python/zlib
toolchain produce identical artifacts regardless of checkout path, source file
mtime, permissions, or inventory order. CI uses Python 3.12 on Ubuntu 24.04.

Artifacts are:

- `dev.cartridge.frequency.tar.gz`: runtime source, assets, manifest, and GPL license.
- `release.json`: `id`, `version`, `url`, `sha256`, `size` (bytes), `min_runtime`, `permissions`.
- `SHA256SUMS`: SHA-256 of the archive and `release.json`.

The workflow validates pull requests, pushes to main, and tags. A tag starts the
release job only after validation succeeds. It uses pinned checkout/setup-python
commits and the GitHub runner's `gh` CLI. Only the release job has
`contents: write`; its sole credential is the built-in `GITHUB_TOKEN`. No custom
secrets or external publishing service are required. Existing releases are never
overwritten automatically. Use a new version for changed payloads.

After publishing, verify the downloaded assets, not just local build output:

```sh
gh release download v1.2.0 --repo Strizzo/frequency-cartridge --dir verified-release
(cd verified-release && shasum -a 256 -c SHA256SUMS)
gh api repos/Strizzo/frequency-cartridge/commits/v1.2.0 --jq .sha
```

Use the published `release.json` and resolved tag commit as the Store catalog
input. GitHub's auto-generated Source code archives are not installable payloads.
A catalog signature is managed by Cartridge, outside this app repository.

## Refreshing the bundled world atlas

`atlas_data.lua` and `assets/atlas/` are reviewed release assets. Frequency 1.2.0
reuses the 1.1.0 atlas unchanged; a controls-only release needs no asset rebuild.
Refresh them only when intentionally updating the geographic snapshot, not at
startup. Install Pillow in a development virtual environment and run:

```sh
python3 -m venv /tmp/frequency-atlas-builder
/tmp/frequency-atlas-builder/bin/pip install Pillow
/tmp/frequency-atlas-builder/bin/python tools/build_atlas.py
```

The builder fetches Radio Browser's geolocated, non-broken station records from
official mirrors, caps input bytes/time/record count, and verifies the pinned
Natural Earth source. Only UUID, latitude, longitude, country code and sanitized
name enter the Lua snapshot; stream URLs are resolved live when tuning.
`assets/attribution.json` records source hashes, dates, per-country counts,
projection, tile bounds and hashes. Rebuild from a saved response using
`--stations-json FILE --shapes FILE --built-at YYYY-MM-DD --fetched-at UTC-TIME`.
Do not commit the full upstream response, private URLs or developer fixtures.

The generated tile inventory is fixed at 85 RGB PNGs for zooms 1, 2, 4 and 8.
Review coverage and country counts, then update `package-files.json` if the
runtime inventory changes. Independent asset tests need only Python's standard
library; Pillow is not needed by CI validation, installation or the handheld.
