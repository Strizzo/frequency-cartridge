#!/usr/bin/env python3
"""Bake Frequency's offline station atlas. Pillow is needed only for this build.

    python3 tools/build_atlas.py
    python3 tools/build_atlas.py --stations-json /tmp/stations.json \
        --shapes /tmp/ne_110m_admin_0_countries.geojson --built-at 2026-10-07

Station rows in atlas_data.lua are positional: {uuid, lat, lon, countrycode, name}.
The full source response (including stream URLs) is never shipped. A saved JSON
response can reproduce a build offline; its SHA is recorded in attribution.
"""

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import NamedTuple
import unicodedata
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


TILE_W, TILE_H = 672, 252
ZOOMS = (1, 2, 4, 8)
CELL_SIZE = 7
MAX_STATIONS = 30_000
SEARCH_LIMIT = 100_000
MAX_RESPONSE_BYTES = 96 * 1024 * 1024
MAX_SHAPES_BYTES = 4 * 1024 * 1024
SOCKET_TIMEOUT = 25
REQUEST_DEADLINE = 60
SERVERS = ("de1.api.radio-browser.info", "de2.api.radio-browser.info", "nl1.api.radio-browser.info")
SEARCH_PATH = "/json/stations/search?has_geo_info=true&hidebroken=true&limit=100000&order=stationuuid"
USER_AGENT = "FrequencyAtlasBuilder/1.0 (build-time offline worldwide radio atlas)"
SHAPES_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_110m_admin_0_countries.geojson"
SHAPES_SHA256 = "6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f"
COLORS = {"ocean": "#192f38", "land": "#466063", "grid": "#29424a",
          "outlines": "#69807b", "peach": "#efb195", "cream": "#efe8d6"}
UUID_RE = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
NUMBER_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
HOST_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.api\.radio-browser\.info\Z")
URL_RE = re.compile(r"(?:\b[a-z][a-z0-9+.-]*://|\bwww\.)[^\s]+", re.IGNORECASE)
CREDENTIAL_RE = re.compile(r"[^\s:]+:[^\s@]+@[^\s]+")


class Station(NamedTuple):
    uuid: str
    lat: float
    lon: float
    countrycode: str
    name: str


class Cluster(NamedTuple):
    x: float
    y: float
    count: int
    radius: float


def sanitize_name(value):
    """Keep readable UTF-8 labels, dropping controls, URL tokens and userinfo."""
    if not isinstance(value, str):
        return "Unnamed station"
    # Bound work even for hostile labels in an otherwise bounded JSON response.
    value = value[:4096]
    value = "".join(" " if unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
                    else c for c in unicodedata.normalize("NFC", value))
    value = URL_RE.sub(" ", value)
    value = CREDENTIAL_RE.sub(" ", value)
    value = " ".join(value.split())[:160]
    value = value.encode("utf-8")[:256].decode("utf-8", errors="ignore").strip()
    return value or "Unnamed station"


def lua_string(value):
    """Lua 5.1+ quoted string, with unambiguous three-digit byte escapes.

    JSON escapes (notably \\uXXXX) are not Lua escapes. UTF-8 bytes are preserved;
    surrogate code points are replaced before encoding. Decimal escapes always
    have three digits so a following numeral cannot extend a control escape.
    """
    parts = ['"']
    for byte in value.encode("utf-8", errors="replace"):
        if byte in (34, 92):
            parts.append("\\" + chr(byte))
        elif byte < 32 or byte == 127:
            parts.append(f"\\{byte:03d}")
        else:
            parts.append(bytes([byte]))
    parts.append('"')
    return b"".join(p.encode("ascii") if isinstance(p, str) else p for p in parts).decode("utf-8")


def coordinate(value, limit):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str):
        value = value.strip()
        if len(value) > 64 or not NUMBER_RE.fullmatch(value):
            return None
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(result) or abs(result) > limit:
        return None
    return 0.0 if result == 0 else result


def normalize_stations(records, cap=MAX_STATIONS):
    """Reject absent/out-of-range coordinates; never synthesize country centers.

    Duplicate UUIDs pick the lexicographically first valid row, independent of
    API order. If the cap is reached, sample across the sorted UUID list instead
    of taking a geographic/chronological prefix, then sort the final rows.
    """
    if not isinstance(records, list) or len(records) > SEARCH_LIMIT:
        raise ValueError("Expected at most 100000 station objects")
    if type(cap) is not int or not 1 <= cap <= MAX_STATIONS:
        raise ValueError("Station cap must be between 1 and 30000")
    by_uuid = {}
    rejected = duplicates = 0
    for record in records:
        if not isinstance(record, dict):
            rejected += 1
            continue
        uid = record.get("stationuuid")
        lat = coordinate(record.get("geo_lat"), 90)
        lon = coordinate(record.get("geo_long"), 180)
        if (not isinstance(uid, str) or not UUID_RE.fullmatch(uid)
                or uid.replace("-", "") == "0" * 32 or lat is None or lon is None
                or record.get("lastcheckok", 1) not in (1, "1")):
            rejected += 1
            continue
        code = record.get("countrycode", "")
        code = code.upper() if isinstance(code, str) and re.fullmatch(r"[a-zA-Z]{2}", code) else ""
        row = Station(uid.lower(), lat, lon, code, sanitize_name(record.get("name")))
        if row.uuid in by_uuid:
            duplicates += 1
            by_uuid[row.uuid] = min(row, by_uuid[row.uuid])
        else:
            by_uuid[row.uuid] = row
    rows = sorted(by_uuid.values())
    valid_count = len(rows)
    if len(rows) > cap:
        rows = [rows[i * len(rows) // cap] for i in range(cap)]
    return rows, {"received": len(records), "rejected": rejected,
                  "duplicates": duplicates, "valid_unique": valid_count,
                  "capped": valid_count - len(rows)}


def lua_number(value):
    if not math.isfinite(value):
        raise ValueError("Non-finite Lua coordinate")
    return "0" if value == 0 else repr(float(value))


def atlas_lua(stations, built_at):
    if date.fromisoformat(built_at).isoformat() != built_at:
        raise ValueError("built_at must be YYYY-MM-DD")
    rows = sorted(stations)
    lines = ["-- Generated by tools/build_atlas.py; offline coordinates only.", "return {",
             f"  schema=1,built_at={lua_string(built_at)},count={len(rows)},",
             "  tile_w=672,tile_h=252,zooms={1,2,4,8},", "  stations={"]
    for s in rows:
        lines.append("    {" + ",".join((lua_string(s.uuid), lua_number(s.lat), lua_number(s.lon),
                                        lua_string(s.countrycode), lua_string(s.name))) + "},")
    return "\n".join(lines + ["  }", "}", ""])


def project(lon, lat, zoom):
    if type(zoom) is not int or zoom not in ZOOMS:
        raise ValueError("Unsupported atlas zoom")
    lon, lat = coordinate(lon, 180), coordinate(lat, 90)
    if lon is None or lat is None:
        raise ValueError("Invalid geographic coordinate")
    w, h = TILE_W * zoom, TILE_H * zoom
    # +180/-90 belong to the last tile, not a nonexistent col/row == zoom.
    return (min((lon + 180) / 360 * w, math.nextafter(float(w), 0)),
            min((90 - lat) / 180 * h, math.nextafter(float(h), 0)))


def tile_bounds(zoom, col, row):
    if (type(zoom) is not int or zoom not in ZOOMS or type(col) is not int
            or type(row) is not int or not (0 <= col < zoom and 0 <= row < zoom)):
        raise ValueError("Invalid tile index")
    return {"west": -180 + col * 360 / zoom, "east": -180 + (col + 1) * 360 / zoom,
            "north": 90 - row * 180 / zoom, "south": 90 - (row + 1) * 180 / zoom}


def cluster_stations(stations, zoom, cell_size=CELL_SIZE):
    """Global screen-pixel grid; centroids use real points, never cell centers.

    The grid is anchored to the whole world, not reset at tile edges. Whole-world
    rendering followed by cropping keeps split markers and backgrounds seamless.
    """
    if type(cell_size) is not int or cell_size < 1:
        raise ValueError("Invalid cluster cell size")
    cells = defaultdict(list)
    for station in sorted(stations):
        x, y = project(station.lon, station.lat, zoom)
        cells[(int(x // cell_size), int(y // cell_size))].append((x, y))
    result = []
    for key in sorted(cells):
        points = cells[key]
        count = len(points)
        result.append(Cluster(math.fsum(p[0] for p in points) / count,
                              math.fsum(p[1] for p in points) / count, count,
                              min(3.0, 1.5 + 0.35 * math.log2(count))))
    return result


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Atlas sources must not redirect")


def read_capped(stream, cap, deadline=None):
    chunks, size = [], 0
    read = getattr(stream, "read1", stream.read)
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Atlas source request exceeded its total deadline")
        chunk = read(min(64 * 1024, cap + 1 - size))
        if not chunk:
            break
        size += len(chunk)
        if size > cap:
            raise ValueError("Atlas source exceeds response byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_bytes(url, cap):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                    "Accept-Encoding": "identity"})
    deadline = time.monotonic() + REQUEST_DEADLINE
    with build_opener(NoRedirect()).open(request, timeout=SOCKET_TIMEOUT) as response:
        length = response.headers.get("Content-Length")
        if length is not None and int(length) > cap:
            raise ValueError("Atlas source exceeds response byte limit")
        if response.headers.get("Content-Encoding", "identity") != "identity":
            raise ValueError("Unexpected compressed atlas source")
        return read_capped(response, cap, deadline)


def read_file(path, cap):
    with Path(path).open("rb") as stream:
        return read_capped(stream, cap)


def search_url(server):
    if not isinstance(server, str) or not HOST_RE.fullmatch(server):
        raise ValueError("Server must be an official *.api.radio-browser.info hostname")
    return "https://" + server + SEARCH_PATH


def fetch_stations(servers=SERVERS):
    servers = tuple(dict.fromkeys(servers))
    if not 1 <= len(servers) <= 3:
        raise ValueError("Use at most three Radio Browser mirrors")
    urls = [search_url(server) for server in servers]
    for url in urls:
        print("Fetching station snapshot from " + url.split("/")[2], flush=True)
        try:
            payload = fetch_bytes(url, MAX_RESPONSE_BYTES)
            # A mirror returning an error object must not replace a valid atlas.
            rows, _ = normalize_stations(json.loads(payload))
            if not rows:
                raise ValueError("Mirror returned no valid geographic stations")
            return payload, url
        except (OSError, URLError, ValueError) as error:
            # Do not log arbitrary server response bodies or exception URLs.
            print("Mirror failed: " + type(error).__name__, file=sys.stderr, flush=True)
    raise ValueError("No Radio Browser mirror supplied a valid bounded snapshot")


def load_shapes(path=None):
    payload = read_file(path, MAX_SHAPES_BYTES) if path else fetch_bytes(SHAPES_URL, MAX_SHAPES_BYTES)
    if hashlib.sha256(payload).hexdigest() != SHAPES_SHA256:
        raise ValueError("Natural Earth v5.1.2 source SHA256 does not match the pinned map source")
    return json.loads(payload)


def render_tiles(stations, shapes, output):
    from PIL import Image, ImageDraw

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    scale = 2
    inventory = []
    for zoom in ZOOMS:
        w, h = TILE_W * zoom, TILE_H * zoom
        image = Image.new("RGB", (w * scale, h * scale), COLORS["ocean"])
        pen = ImageDraw.Draw(image)

        def xy(lon, lat):
            return ((lon + 180) / 360 * w * scale, (90 - lat) / 180 * h * scale)

        for lon in range(-150, 180, 30):
            pen.line([xy(lon, 90), xy(lon, -90)], fill=COLORS["grid"], width=scale)
        for lat in range(-60, 90, 30):
            pen.line([xy(-180, lat), xy(180, lat)], fill=COLORS["grid"], width=scale)
        for feature in shapes["features"]:
            geometry = feature.get("geometry")
            if not geometry:
                continue
            if geometry["type"] == "Polygon":
                polygons = [geometry["coordinates"]]
            elif geometry["type"] == "MultiPolygon":
                polygons = geometry["coordinates"]
            else:
                raise ValueError("Unexpected Natural Earth geometry")
            for polygon in polygons:
                for index, ring in enumerate(polygon):
                    points = [xy(*point[:2]) for point in ring]
                    pen.polygon(points, fill=COLORS["land"] if index == 0 else COLORS["ocean"])
                    pen.line(points, fill=COLORS["outlines"], width=scale)

        clusters = cluster_stations(stations, zoom)
        for cluster in clusters:
            x, y, _, radius = cluster
            # Wrap a marker cut by the antimeridian onto the opposite edge.
            centers = [x]
            if x - radius < 0:
                centers.append(x + w)
            if x + radius >= w:
                centers.append(x - w)
            for center in centers:
                box = tuple(v * scale for v in (center - radius, y - radius,
                                                 center + radius, y + radius))
                pen.ellipse(box, fill=COLORS["cream"] if cluster.count >= 8 else COLORS["peach"],
                            outline=COLORS["ocean"], width=1)
        image = image.resize((w, h), Image.Resampling.LANCZOS)
        for col in range(zoom):
            for row in range(zoom):
                filename = f"z{zoom}-{col}-{row}.png"
                tile = image.crop((col * TILE_W, row * TILE_H, (col + 1) * TILE_W, (row + 1) * TILE_H))
                path = output / filename
                tile.save(path, optimize=True)
                inventory.append({"file": "assets/atlas/" + filename, "zoom": zoom,
                                  "col": col, "row": row, "bounds": tile_bounds(zoom, col, row),
                                  "bytes": path.stat().st_size,
                                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        image.close()
        print(f"Rendered zoom {zoom}: {zoom * zoom} RGB tiles, {len(clusters)} clusters", flush=True)
    return inventory


def build(output, payload, source, shapes, built_at, fetched_at, cap=MAX_STATIONS, offline=False):
    stations, filtering = normalize_stations(json.loads(payload), cap)
    if not stations:
        raise ValueError("Refusing to build an atlas with no valid station coordinates")
    lua = atlas_lua(stations, built_at).encode("utf-8")
    output = Path(output)
    attribution_path = output / "assets/attribution.json"
    # Preserve the map, icon and directory provenance from the existing assets.
    metadata = json.loads(attribution_path.read_text("utf-8")) if attribution_path.exists() else {}
    with tempfile.TemporaryDirectory(prefix="frequency-atlas-") as temp:
        temp = Path(temp)
        tiles = render_tiles(stations, shapes, temp)
        metadata["atlas"] = {
            "schema": 1, "built_at": built_at, "fetched_at": fetched_at,
            "source": source, "response_sha256": hashlib.sha256(payload).hexdigest(),
            "response_bytes": len(payload), "input_mode": "offline-input" if offline else "live-build",
            "license": "Radio Browser community database; public domain",
            "count": len(stations), "per_country": dict(sorted(Counter(s.countrycode for s in stations).items())),
            "filtering": filtering, "max_stations": cap,
            "station_fields": ["uuid", "lat", "lon", "countrycode", "name"],
            "snapshot_sha256": hashlib.sha256(lua).hexdigest(), "snapshot_bytes": len(lua),
            "tile_w": TILE_W, "tile_h": TILE_H, "zooms": list(ZOOMS), "tile_count": len(tiles),
            "projection": {
                "name": "Equirectangular", "world": {"west": -180, "east": 180, "north": 90, "south": -90},
                "x": "(lon+180)/360*672*zoom", "y": "(90-lat)/180*252*zoom",
                "origin": "northwest; x east, y south",
                "tile": "assets/atlas/z{zoom}-{col}-{row}.png; col,row are integers in [0,zoom-1]",
                "tile_x": "world_x-col*672", "tile_y": "world_y-row*252",
                "edge_policy": "+180 and -90 clamp inside the last tile; marker artwork wraps at the antimeridian",
                "viewport": "672x252 pixels at native scale; at most four cropped tile blits per frame"
            },
            "clusters": {"cell_pixels": CELL_SIZE, "anchor": "whole-world pixel origin",
                         "position": "mean of actual projected station points in each cell",
                         "radius_pixels": [1.5, 3.0], "colors": COLORS},
            "background": {"source": SHAPES_URL, "version": "5.1.2", "license": "Public domain",
                           "source_sha256": SHAPES_SHA256},
            "notes": "Offline build snapshot. No launch-time catalogue fetch, stream URLs, logos or synthetic coordinates. Country codes and coordinates are contributor-supplied.",
            "tiles": tiles
        }
        atlas_dir = output / "assets/atlas"
        atlas_dir.mkdir(parents=True, exist_ok=True)
        for tile in tiles:
            (atlas_dir / Path(tile["file"]).name).write_bytes((temp / Path(tile["file"]).name).read_bytes())
        (output / "atlas_data.lua").write_bytes(lua)
        attribution_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata["atlas"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--stations-json", type=Path, help="Rebuild offline from a saved Radio Browser response")
    parser.add_argument("--shapes", type=Path, help="Use local SHA-verified Natural Earth v5.1.2 GeoJSON")
    parser.add_argument("--server", action="append", help="Official API hostname; up to three mirrors")
    parser.add_argument("--built-at", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--fetched-at", help="Original response time for an offline rebuild, ISO 8601 UTC")
    parser.add_argument("--max-stations", type=int, default=MAX_STATIONS)
    args = parser.parse_args(argv)
    try:
        source = search_url((args.server or SERVERS)[0])
        # Validate options before either network access or output changes.
        atlas_lua([], args.built_at)
        normalize_stations([], args.max_stations)
        servers = args.server or SERVERS
        if len(servers) > 3:
            raise ValueError("Use at most three Radio Browser mirrors")
        for server in servers:
            search_url(server)
        if args.fetched_at:
            parsed = datetime.fromisoformat(args.fetched_at.replace("Z", "+00:00"))
            if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
                raise ValueError("fetched_at must have UTC timezone")
            if not args.stations_json:
                raise ValueError("fetched_at is only for offline input")
        if args.stations_json:
            payload = read_file(args.stations_json, MAX_RESPONSE_BYTES)
        else:
            payload, source = fetch_stations(servers)
        fetched_at = args.fetched_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        shapes = load_shapes(args.shapes)
        metadata = build(args.output, payload, source, shapes, args.built_at, fetched_at,
                         args.max_stations, bool(args.stations_json))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Atlas build failed: {error}\n")
    print(json.dumps({"count": metadata["count"], "Italy": metadata["per_country"].get("IT", 0),
                      "snapshot_bytes": metadata["snapshot_bytes"], "tiles": metadata["tile_count"],
                      "tile_bytes": sum(t["bytes"] for t in metadata["tiles"]),
                      "response_sha256": metadata["response_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
