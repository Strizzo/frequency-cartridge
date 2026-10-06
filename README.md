# Frequency

A controller-operated atlas of internet radio. The bundled world map contains
**13,179 reported station locations across 182 country codes**, including
**215 in Italy** (snapshot: 7 October 2026). Coverage appears immediately and stays
visible offline. Country, genre and name searches use Radio Browser's live
100-record pages independently of the map. Stations without coordinates remain
available through search; the app never substitutes invented locations.

- In lists, countries, menus and settings: left stick or D-pad navigates. In station lists, right enters the map and left opens countries.
- On the map: left stick pans at a speed proportional to its deflection; D-pad still moves the cursor.
- Right stick up/down or X/Y zooms in/out at 1×, 2×, 4× and 8×. Recenter the right stick between zoom steps.
- L1/R1 choose nearby map stations; A fetches current stream details and tunes; B returns to the list.
- In lists: A plays/pauses, X saves a favorite, Y searches, and L1/R1 change genre.
- L2/R2 adjust volume. Start opens the menu, including Save station for map selections.
- Select exits; when the keyboard is open, cancel editing instead.

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

Requires **Cartridge 0.6.2 or newer**. App ID: `dev.cartridge.frequency`.
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

Simulator stick keys: **I/J/K/L = left up/left/down/right**, and
**T/F/G/H = right up/left/down/right**. Existing digital button bindings still work.
Release the stick keys to recenter. Opening a menu or keyboard, or changing views,
stops stick motion; a stick held through that change must recenter before reuse.

## Development and releases

Python 3.12+ and Lua 5.4 are sufficient for the independent checks:

```sh
python3 tools/package.py --check
find . -type f -name '*.lua' -not -path './.git/*' -print0 | xargs -0 -n 1 luac -p
lua tests/unit.lua
lua tests/atlas.lua
lua tests/app_atlas.lua
lua tests/app_sticks.lua
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tools/package.py --tag v1.2.0
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
