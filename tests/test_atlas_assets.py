"""Focused atlas validation. These tests require only the Python standard library."""
from collections import Counter
from datetime import date, datetime
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import re
import struct
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("atlas_builder", ROOT / "tools/build_atlas.py")
atlas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(atlas)
UUID = "12345678-1234-1234-1234-123456789abc"
QUOTED = r'"(?:[^"\\\r\n]|\\(?:[0-9]{3}|["\\]))*"'
LUA_ROW = re.compile(r"^    \{(" + QUOTED + r"),([^,]+),([^,]+),(" + QUOTED + r"),(" + QUOTED + r")\},$")


def record(**changes):
    row = {"stationuuid": UUID, "geo_lat": 41.9028, "geo_long": 12.4964,
           "name": "Radio Roma", "countrycode": "IT", "lastcheckok": 1}
    row.update(changes)
    return row


def decode_lua_string(value):
    def escape(match):
        token = match.group(1)
        return chr(int(token)) if token.isdigit() else token
    return re.sub(r'\\([0-9]{3}|["\\])', escape, value[1:-1])


def snapshot_rows(text):
    rows = []
    for line in text.splitlines():
        if line.startswith("    {"):
            match = LUA_ROW.fullmatch(line)
            if not match:
                raise AssertionError("Invalid or injected Lua station row: " + line[:120])
            uid, lat, lon, code, name = match.groups()
            rows.append(atlas.Station(decode_lua_string(uid), float(lat), float(lon),
                                      decode_lua_string(code), decode_lua_string(name)))
    return rows


class AtlasBuilderTests(unittest.TestCase):
    def test_lua_escaping_roundtrips_hostile_control_unicode_and_digit_names(self):
        name = '"};os.execute("injected");--\\\x00' + '123\n\r\t\x1f\x7f雪📻\u2028'
        quoted = atlas.lua_string(name)
        self.assertRegex(quoted, "^" + QUOTED + "$")
        self.assertEqual(decode_lua_string(quoted), name)
        self.assertIn("\\000123", quoted)
        self.assertNotIn("\n", quoted)
        self.assertNotIn("\\u", quoted)
        self.assertEqual(decode_lua_string(atlas.lua_string("\ud800")), "?")

    def test_labels_strip_controls_bidi_surrogates_and_urls_without_losing_unicode(self):
        hostile = 'Radio\x00\n"Roma"\u202e\ud800 Café 雪 📻 https://user:TOPSECRET@example.invalid/live?token=SECRET www.example.invalid user:password@host'
        label = atlas.sanitize_name(hostile)
        self.assertEqual(label, 'Radio "Roma" Café 雪 📻')
        self.assertLessEqual(len(atlas.sanitize_name("雪" * 10000).encode()), 256)
        self.assertEqual(atlas.sanitize_name(None), "Unnamed station")
        self.assertEqual(atlas.sanitize_name("https://user:SECRET@host/stream"), "Unnamed station")
        self.assertEqual(atlas.sanitize_name("Cafe\u0301"), "Café")

    def test_uuid_validation_and_case_normalization(self):
        for uid in (None, 123, "", UUID + '"};error("bad")', "../station", "not-a-uuid",
                    "00000000-0000-0000-0000-000000000000", UUID.replace("-", "")):
            with self.subTest(uid=uid):
                rows, _ = atlas.normalize_stations([record(stationuuid=uid)])
                self.assertEqual(rows, [])
        rows, _ = atlas.normalize_stations([record(stationuuid=UUID.upper())])
        self.assertEqual(rows[0].uuid, UUID)

    def test_only_finite_actual_coordinates_including_zero_and_poles(self):
        for field, limit in (("geo_lat", 90), ("geo_long", 180)):
            for value in (None, True, False, "", "NaN", "Inf", "-Infinity", math.nan,
                          math.inf, -math.inf, limit + 0.01, -limit - 0.01, [], {}, "1e9999",
                          "1;os.execute('bad')", "0x10", 10 ** 1000):
                with self.subTest(field=field, value=str(value)[:50]):
                    self.assertEqual(atlas.normalize_stations([record(**{field: value})])[0], [])
            missing = record()
            del missing[field]
            self.assertEqual(atlas.normalize_stations([missing])[0], [])
        for lat, lon in ((0, 0), (-90, -180), (90, 180), ("4.19e1", "12.5")):
            rows, _ = atlas.normalize_stations([record(geo_lat=lat, geo_long=lon)])
            self.assertEqual((rows[0].lat, rows[0].lon), (float(lat), float(lon)))
        self.assertEqual(atlas.normalize_stations([record(lastcheckok=0)])[0], [])

    def test_snapshot_is_deterministic_capped_and_contains_only_allowed_fields(self):
        records = [record(stationuuid=f"{i:08x}-1234-1234-1234-123456789abc",
                          name='Safe "name"\\雪', url="https://USER:SECRET@example.invalid/live",
                          url_resolved="https://host/stream?token=SECRET", favicon="https://host/logo",
                          homepage="https://host/", password="SECRET", countrycode="it")
                   for i in range(12)]
        records += [record(stationuuid=records[0]["stationuuid"], name="duplicate"), None,
                    record(stationuuid="bad"), record(geo_lat=None)]
        first, stats = atlas.normalize_stations(records, cap=5)
        second, other_stats = atlas.normalize_stations(list(reversed(records)), cap=5)
        self.assertEqual(first, second)
        self.assertEqual(stats, other_stats)
        self.assertEqual(len(first), 5)
        self.assertEqual(stats, {"received": 16, "rejected": 3, "duplicates": 1,
                                 "valid_unique": 12, "capped": 7})
        self.assertEqual(first, sorted(first))
        text = atlas.atlas_lua(first, "2026-10-07")
        self.assertEqual(snapshot_rows(text), first)
        self.assertNotIn("SECRET", text)
        self.assertNotIn("https://", text)
        self.assertIn("schema=1,built_at=\"2026-10-07\",count=5", text)
        self.assertIn("tile_w=672,tile_h=252,zooms={1,2,4,8}", text)
        for cap in (0, True, 30001):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                atlas.normalize_stations(records, cap)
        with self.assertRaises(ValueError):
            atlas.normalize_stations({"error": "bad response"})
        with self.assertRaises(ValueError):
            atlas.atlas_lua(first, '2026-10-07"};error("bad")')

    def test_invalid_country_and_name_do_not_become_lua_source(self):
        rows, _ = atlas.normalize_stations([record(countrycode='IT"};error("bad")',
                                                  name='"};error("bad");--')])
        self.assertEqual(rows[0].countrycode, "")
        self.assertEqual(snapshot_rows(atlas.atlas_lua(rows, "2026-10-07")), rows)
        for code in (None, "ITALY", "\u0131T", "\u00df"):
            with self.subTest(code=code):
                self.assertEqual(atlas.normalize_stations([record(countrycode=code)])[0][0].countrycode, "")

    def test_deterministic_clusters_conserve_points_and_use_actual_centroids(self):
        rows = [atlas.Station(f"{i:08x}-1234-1234-1234-123456789abc", 0, lon, "", "")
                for i, lon in enumerate((-1, -0.5, 0, 0.5, 180, -180))]
        for zoom in atlas.ZOOMS:
            clusters = atlas.cluster_stations(rows, zoom)
            self.assertEqual(clusters, atlas.cluster_stations(list(reversed(rows)), zoom))
            self.assertEqual(sum(c.count for c in clusters), len(rows))
            for c in clusters:
                self.assertTrue(0 <= c.x < atlas.TILE_W * zoom)
                self.assertTrue(0 <= c.y < atlas.TILE_H * zoom)
                self.assertTrue(1.5 <= c.radius <= 3.0)
        same = [atlas.Station(str(i), 41.9, 12.5, "IT", "") for i in range(100)]
        cluster = atlas.cluster_stations(same, 4)[0]
        x, y = atlas.project(12.5, 41.9, 4)
        self.assertAlmostEqual(cluster.x, x)
        self.assertAlmostEqual(cluster.y, y)
        self.assertEqual((cluster.count, cluster.radius), (100, 3.0))
        self.assertEqual(atlas.cluster_stations([], 1), [])

    def test_projection_and_tile_bounds_cover_the_world_at_every_zoom(self):
        for zoom in atlas.ZOOMS:
            self.assertEqual(atlas.project(-180, 90, zoom), (0, 0))
            self.assertEqual(atlas.project(0, 0, zoom), (336 * zoom, 126 * zoom))
            x, y = atlas.project(180, -90, zoom)
            self.assertEqual((int(x // 672), int(y // 252)), (zoom - 1, zoom - 1))
            for col in range(zoom):
                for row in range(zoom):
                    b = atlas.tile_bounds(zoom, col, row)
                    self.assertAlmostEqual(b["east"] - b["west"], 360 / zoom)
                    self.assertAlmostEqual(b["north"] - b["south"], 180 / zoom)
                    mid = atlas.project((b["west"] + b["east"]) / 2,
                                        (b["north"] + b["south"]) / 2, zoom)
                    self.assertEqual(mid, (col * 672 + 336, row * 252 + 126))
        for args in ((3, 0, 0), (1, 1, 0), (2, -1, 0), (4, 0, 4), (True, 0, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                atlas.tile_bounds(*args)

    def test_fetch_limits_deadline_and_official_source_contract(self):
        self.assertEqual(atlas.read_capped(io.BytesIO(b"abcd"), 4), b"abcd")
        with self.assertRaises(ValueError):
            atlas.read_capped(io.BytesIO(b"abcde"), 4)
        with self.assertRaises(TimeoutError):
            atlas.read_capped(io.BytesIO(b"abcd"), 4, deadline=0)
        self.assertEqual(atlas.search_url("de1.api.radio-browser.info"),
                         "https://de1.api.radio-browser.info" + atlas.SEARCH_PATH)
        for host in ("https://de1.api.radio-browser.info", "user:secret@de1.api.radio-browser.info",
                     "api.radio-browser.info.evil.invalid", "evil.invalid", "a..api.radio-browser.info",
                     "../de1.api.radio-browser.info", "de1.api.radio-browser.info:443"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                atlas.search_url(host)
        with patch.object(atlas, "fetch_bytes", return_value=b'{"error":"try another mirror"}') as fetch, \
                patch("sys.stdout", new=io.StringIO()), patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(ValueError):
                atlas.fetch_stations()
            self.assertEqual(fetch.call_count, 3)
        with patch.object(atlas, "fetch_bytes", return_value=b"not pinned shapes"):
            with self.assertRaisesRegex(ValueError, "SHA256"):
                atlas.load_shapes()

    def test_build_preserves_existing_attribution_and_keeps_secrets_out(self):
        original = {"map": {"source_sha256": "existing"}, "icon": {"creator": "Team"},
                    "directory": {"notes": "existing notes"}, "other": {"keep": True}}
        payload = json.dumps([record(url="https://user:SECRET@host/live",
                                     name="Radio https://host/?token=SECRET")]).encode()

        def fake_render(stations, shapes, output):
            target = Path(output) / "z1-0-0.png"
            target.write_bytes(b"test tile")
            return [{"file": "assets/atlas/z1-0-0.png", "bytes": 9}]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "assets").mkdir()
            (root / "assets/attribution.json").write_text(json.dumps(original))
            with patch.object(atlas, "render_tiles", side_effect=fake_render):
                result = atlas.build(root, payload, atlas.search_url(atlas.SERVERS[0]), {},
                                     "2026-10-07", "2026-10-07T12:00:00Z")
            saved = json.loads((root / "assets/attribution.json").read_text())
            for key, value in original.items():
                self.assertEqual(saved[key], value)
            self.assertEqual(result["per_country"], {"IT": 1})
            self.assertEqual(result["response_sha256"], hashlib.sha256(payload).hexdigest())
            self.assertNotIn("SECRET", json.dumps(saved))
            self.assertNotIn("SECRET", (root / "atlas_data.lua").read_text())


@unittest.skipUnless((ROOT / "atlas_data.lua").exists(), "Generated live atlas not present")
class GeneratedAtlasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = (ROOT / "atlas_data.lua").read_bytes()
        cls.rows = snapshot_rows(cls.payload.decode("utf-8"))
        cls.metadata = json.loads((ROOT / "assets/attribution.json").read_text())["atlas"]

    def test_snapshot_schema_counts_coordinates_and_country_coverage(self):
        meta = self.metadata
        self.assertEqual(meta["schema"], 1)
        self.assertEqual(date.fromisoformat(meta["built_at"]).isoformat(), meta["built_at"])
        self.assertIsNotNone(datetime.fromisoformat(meta["fetched_at"].replace("Z", "+00:00")).tzinfo)
        self.assertEqual(meta["snapshot_sha256"], hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(meta["snapshot_bytes"], len(self.payload))
        self.assertEqual(len(self.rows), meta["count"])
        self.assertTrue(0 < len(self.rows) <= 30000)
        self.assertEqual(self.rows, sorted(self.rows))
        self.assertEqual(len(set(s.uuid for s in self.rows)), len(self.rows))
        self.assertEqual(dict(Counter(s.countrycode for s in self.rows)), meta["per_country"])
        self.assertEqual(meta["station_fields"], ["uuid", "lat", "lon", "countrycode", "name"])
        if meta["input_mode"] == "live-build":
            # Deliberately broad; don't freeze the changing community directory.
            self.assertGreater(len(self.rows), 1000)
            self.assertGreater(meta["per_country"].get("IT", 0), 20)
            self.assertGreater(len(meta["per_country"]), 50)
            italy = [s for s in self.rows if s.countrycode == "IT" and 35 <= s.lat <= 48 and 5 <= s.lon <= 20]
            self.assertGreater(len(italy), 20)
            self.assertGreater(len({(s.lat, s.lon) for s in italy}), 10)
        for row in self.rows:
            self.assertRegex(row.uuid, atlas.UUID_RE)
            self.assertTrue(math.isfinite(row.lat) and abs(row.lat) <= 90)
            self.assertTrue(math.isfinite(row.lon) and abs(row.lon) <= 180)
            self.assertEqual(atlas.sanitize_name(row.name), row.name)
        self.assertRegex(meta["response_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotRegex(self.payload.decode(), atlas.URL_RE)
        self.assertNotRegex(self.payload.decode(), atlas.CREDENTIAL_RE)
        f = meta["filtering"]
        self.assertEqual(f["received"], f["rejected"] + f["duplicates"] + f["valid_unique"])
        self.assertEqual(meta["count"], f["valid_unique"] - f["capped"])

    def test_complete_rgb_png_tile_inventory_and_projection(self):
        meta = self.metadata
        self.assertEqual((meta["tile_w"], meta["tile_h"], meta["zooms"]), (672, 252, [1, 2, 4, 8]))
        expected = {f"assets/atlas/z{z}-{c}-{r}.png" for z in atlas.ZOOMS
                    for c in range(z) for r in range(z)}
        self.assertEqual(meta["tile_count"], 85)
        self.assertEqual(len(meta["tiles"]), 85)
        self.assertEqual({t["file"] for t in meta["tiles"]}, expected)
        self.assertEqual({str(p.relative_to(ROOT)) for p in (ROOT / "assets/atlas").glob("*.png")}, expected)
        self.assertEqual(meta["background"]["source_sha256"], atlas.SHAPES_SHA256)
        self.assertEqual(meta["clusters"]["cell_pixels"], 7)
        self.assertEqual(meta["projection"]["x"], "(lon+180)/360*672*zoom")
        self.assertEqual(meta["projection"]["y"], "(90-lat)/180*252*zoom")
        for tile in meta["tiles"]:
            self.assertEqual(tile["bounds"], atlas.tile_bounds(tile["zoom"], tile["col"], tile["row"]))
            payload = (ROOT / tile["file"]).read_bytes()
            self.assertEqual(len(payload), tile["bytes"])
            self.assertEqual(hashlib.sha256(payload).hexdigest(), tile["sha256"])
            self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(payload[12:16], b"IHDR")
            # IHDR: dimensions, bit depth, color type; RGB, never indexed/RGBA.
            self.assertEqual(struct.unpack(">IIBB", payload[16:26]), (672, 252, 8, 2))


if __name__ == "__main__":
    unittest.main()
