# Release maintenance

The default branch is `main`. Release tags are `vMAJOR.MINOR.PATCH`, matching
`cartridge.json` exactly. The app ID is fixed at `dev.cartridge.frequency` and this
release line requires `min_runtime: "0.6.0"`. Update the manifest version and
release notes, review `package-files.json`, and run the README checks before
committing and pushing a new tag.

```sh
python3 tools/package.py --tag v1.0.0
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
gh release download v1.0.0 --repo Strizzo/frequency-cartridge --dir verified-release
(cd verified-release && shasum -a 256 -c SHA256SUMS)
gh api repos/Strizzo/frequency-cartridge/commits/v1.0.0 --jq .sha
```

Use the published `release.json` and resolved tag commit as the Store catalog
input. GitHub's auto-generated Source code archives are not installable payloads.
A catalog signature is managed by Cartridge, outside this app repository.
