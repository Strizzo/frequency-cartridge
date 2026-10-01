# Frequency

A controller-operated atlas of internet radio. Browse Radio Browser by country,
genre or station name, navigate reported map locations, save favorites, and play
streams directly from broadcasters. Map pins appear only where the directory
provides coordinates; stations without coordinates remain available in the list.

- D-pad: choose stations or navigate the map/menus.
- A: play, pause or resume. B: stop or go back.
- X: save/remove a favorite. Y: search.
- L1/R1: genre. L2/R2: volume.
- Start: countries, favorites, history, paging, settings and station details.
- Select: exit; when the keyboard is open, cancel editing instead.

The app never autoplays on launch. Favorites and the last directory page are
cached, but listening needs internet access. Failed stations can be retried or
replaced with another station. Settings also accept a custom direct stream URL.

Native decoding supports MP3, AAC-LC, Ogg Vorbis, FLAC and WAV/PCM. HLS, HE-AAC
and Opus are unsupported. Prefer MP3 when a station fails. Radio Browser labels
cannot guarantee codec compatibility or access from every region. The firmware
needs `curl` for streaming transport.

The map uses public-domain Natural Earth data; station metadata comes from
Radio Browser. Stream content and station marks belong to their owners.
See the [API, storage, attribution, and integration guide](docs/frequency.md).

## Install and run

Requires **Cartridge 0.6.0 or newer**. App ID: `dev.cartridge.frequency`.
The release requires these runtime permissions: `network`, `audio`, `storage`.

Download [`dev.cartridge.frequency.tar.gz`](https://github.com/Strizzo/frequency-cartridge/releases/latest)
and `SHA256SUMS` from the same release. The archive contains `cartridge.json`,
`main.lua`, Lua modules, artwork, and `LICENSE` directly at its root. Verify its
SHA-256 against `SHA256SUMS` (or the Store catalog) before installing through
Cartridge's Store. `release.json` supplies the versioned URL, byte size, hash,
minimum runtime, and permissions for catalog integration.

To run a development checkout with the Cartridge simulator:

```sh
cd /path/to/Cartridge
./sim.sh app /path/to/frequency-cartridge
```

## Development and releases

Python 3.12+ and Lua 5.4 are sufficient for the independent checks:

```sh
python3 tools/package.py --check
find . -type f -name '*.lua' -not -path './.git/*' -print0 | xargs -0 -n 1 luac -p
lua tests/unit.lua
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tools/package.py --tag v1.0.0
```

On Linux, Lua executables may be named `lua5.4` and `luac5.4`.
The Python packager has no third-party dependencies. `package-files.json` is the
reviewable runtime payload inventory; it must include every root Lua module and
all files in `assets/`. Development tools, tests, docs, and this README stay out
of release archives. See [release maintenance](docs/releasing.md).

CI runs syntax checks, focused pure-Lua behavior tests, manifest validation,
and archive integrity/reproducibility tests. Shared runtime, native audio/HTTP,
SDL rendering, and device integration tests remain in
[Cartridge](https://github.com/Strizzo/Cartridge/blob/d17e6f9074eb238d9e604e36e386d79d11f62985/crates/cartridge-lua/tests/frequency.rs);
see [the integration guide](docs/frequency.md) for their commands and limits.

## License and origin

GPL-3.0; see [LICENSE](LICENSE), copied verbatim from Cartridge.
Extracted from [Cartridge `d17e6f9074eb`](https://github.com/Strizzo/Cartridge/blob/d17e6f9074eb238d9e604e36e386d79d11f62985/lua_cartridges/frequency).
Existing author credits and app-specific data/artwork attribution are retained.
