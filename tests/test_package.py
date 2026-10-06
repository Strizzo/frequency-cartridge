"""Release-contract and hostile filesystem regression tests; no runtime needed."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("packager", ROOT / "tools/package.py")
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "source"
        self.root.mkdir()
        self.names = json.loads((ROOT / "package-files.json").read_text())
        for name in self.names + ["package-files.json"]:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        self.version = json.loads((self.root / "cartridge.json").read_text())["version"]
        self.tag = f"v{self.version}"
        self.out = self.base / "release"

    def change_manifest(self, **changes):
        p = self.root / "cartridge.json"
        manifest = json.loads(p.read_text())
        manifest.update(changes)
        p.write_text(json.dumps(manifest))

    def change_inventory(self, names):
        (self.root / "package-files.json").write_text(json.dumps(names))

    def test_archive_integrity_metadata_and_checksums(self):
        meta = packager.build(self.root, self.out, self.tag)
        package = self.out / f"{packager.APP_ID}.tar.gz"
        self.assertEqual(set(meta), {"id", "version", "url", "sha256", "size", "min_runtime", "permissions"})
        self.assertEqual(meta["id"], packager.APP_ID)
        self.assertEqual(meta["version"], self.version)
        self.assertEqual(meta["min_runtime"], "0.6.2")
        self.assertEqual(meta["url"], f"https://github.com/{packager.REPOSITORY}/releases/download/{self.tag}/{package.name}")
        self.assertEqual(meta["sha256"], hashlib.sha256(package.read_bytes()).hexdigest())
        self.assertEqual(meta["size"], package.stat().st_size)
        self.assertEqual(json.loads((self.out / "release.json").read_text()), meta)
        with tarfile.open(package, "r:gz") as archive:
            self.assertEqual(archive.getnames(), sorted(self.names))
            for member in archive.getmembers():
                self.assertTrue(member.isfile())
                self.assertFalse(member.issym() or member.islnk())
                self.assertFalse(member.name.startswith(("/", "./")))
                self.assertNotIn("..", member.name.split("/"))
                self.assertEqual((member.uid, member.gid, member.mtime, member.mode), (0, 0, 0, 0o644))
                self.assertEqual(archive.extractfile(member).read(), (self.root / member.name).read_bytes())
            manifest = json.load(archive.extractfile("cartridge.json"))
            self.assertEqual(manifest["permissions"], meta["permissions"])
        for line in (self.out / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ", 1)
            self.assertEqual(digest, hashlib.sha256((self.out / name).read_bytes()).hexdigest())

    def test_reproducible_across_file_metadata_order_and_output_paths(self):
        first = packager.build(self.root, self.out, self.tag)
        for name in self.names:
            path = self.root / name
            os.utime(path, (1711111111, 1711111111))
            path.chmod(0o755)
        self.change_inventory(list(reversed(self.names)))
        other = self.base / "elsewhere"
        self.assertEqual(first, packager.build(self.root, other, self.tag))
        for path in self.out.iterdir():
            self.assertEqual(path.read_bytes(), (other / path.name).read_bytes())

    def test_rejects_identity_version_runtime_and_permission_errors(self):
        original = (self.root / "cartridge.json").read_bytes()
        changes = [{"id": "dev.cartridge.wrong"}, {"version": "01.0.0"}, {"version": "v1.0.0"},
                   {"version": "1.0.0/../../escape"}, {"version": 1}, {"min_runtime": "0.5.0"},
                   {"min_runtime": "0.6.0"}, {"min_runtime": "0.6.1"}, {"min_runtime": None},
                   {"permissions": ["network", "network"]},
                   {"permissions": ["shell"]}, {"permissions": [{}]}, {"entry": "../main.lua"}]
        for change in changes:
            with self.subTest(change=change):
                (self.root / "cartridge.json").write_bytes(original)
                self.change_manifest(**change)
                with self.assertRaises(ValueError):
                    packager.build(self.root, self.out, self.tag)
                self.assertFalse(self.out.exists())

    def test_tag_required_and_must_match(self):
        for tag in (None, "1.0.0", "v9.9.9", "v1.0.0/escape"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                packager.build(self.root, self.out, tag)

    def test_rejects_traversal_absolute_ambiguous_and_duplicate_paths(self):
        for path in ("../escape", "/etc/passwd", "assets/../icon.png", "./main.lua", "assets//file", "assets\\file", "main.lua"):
            with self.subTest(path=path):
                self.change_inventory(self.names + [path])
                with self.assertRaises((ValueError, OSError)):
                    packager.validate(self.root, self.tag)

    def test_rejects_development_files_even_if_inventory_lists_them(self):
        for path in ("README.md", "tests/secret.lua", "tools/helper.py", ".env"):
            with self.subTest(path=path):
                target = self.root / path
                target.parent.mkdir(exist_ok=True)
                target.write_text("must never ship")
                self.change_inventory(self.names + [path])
                with self.assertRaises(ValueError):
                    packager.validate(self.root)

    def test_excludes_development_files(self):
        (self.root / "README.md").write_text("development only")
        (self.root / ".env").write_text("development only")
        _, payload = packager.validate(self.root)
        self.assertNotIn("README.md", payload)
        self.assertNotIn(".env", payload)

    def test_detects_missing_or_unlisted_modules_assets_and_license(self):
        for name in ("main.lua", "icon.png", "LICENSE"):
            with self.subTest(name=name):
                self.change_inventory([p for p in self.names if p != name])
                with self.assertRaises(ValueError):
                    packager.validate(self.root)
        self.change_inventory(self.names)
        (self.root / "forgotten.lua").write_text("return {}")
        with self.assertRaisesRegex(ValueError, "inventory"):
            packager.validate(self.root)
        (self.root / "forgotten.lua").unlink()
        (self.root / "assets").mkdir(exist_ok=True)
        (self.root / "assets/forgotten.png").write_bytes(b"image")
        with self.assertRaisesRegex(ValueError, "inventory"):
            packager.validate(self.root)

    def test_detects_broken_lua_and_asset_references(self):
        entry = self.root / "main.lua"
        original = entry.read_text()
        for extra in ("\nrequire('missing_module')", "\nscreen.draw_image('assets/missing.png', 0, 0)"):
            with self.subTest(extra=extra):
                entry.write_text(original + extra)
                with self.assertRaisesRegex(ValueError, "Missing"):
                    packager.validate(self.root)

    def test_numeric_tile_patterns_require_matching_inventory(self):
        entry = self.root / "main.lua"
        original = entry.read_text()
        entry.write_text(original + "\nscreen.draw_image(string.format('assets/atlas/z%d-%d-%d.png', 1, 0, 0), 0, 0)")
        packager.validate(self.root)
        for pattern in ("assets/atlas/missing-%d.png", "assets/atlas/z%s-%d-%d.png"):
            with self.subTest(pattern=pattern):
                entry.write_text(original + f"\nscreen.draw_image('{pattern}', 0, 0)")
                with self.assertRaisesRegex(ValueError, "Missing asset"):
                    packager.validate(self.root)

    def test_rejects_symlinks_and_hardlinks(self):
        target = self.root / "main.lua"
        target.unlink()
        target.symlink_to(ROOT / "main.lua")
        with self.assertRaises(ValueError):
            packager.validate(self.root)
        target.unlink()
        os.link(self.root / "LICENSE", target)
        with self.assertRaises(ValueError):
            packager.validate(self.root)

    def test_rejects_symlinked_asset_directory(self):
        assets = self.root / "assets"
        if assets.exists():
            shutil.rmtree(assets)
        assets.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(ValueError):
            packager.validate(self.root)

    def test_rejects_special_files(self):
        path = self.root / "main.lua"
        path.unlink()
        os.mkfifo(path)
        with self.assertRaises(ValueError):
            packager.validate(self.root)

    def test_rejects_duplicate_manifest_keys(self):
        path = self.root / "cartridge.json"
        path.write_text(path.read_text().replace('{', '{"id":"wrong",', 1))
        with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
            packager.validate(self.root)

    def test_does_not_follow_output_links(self):
        self.out.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            packager.build(self.root, self.out, self.tag)
        self.out.unlink()
        self.out.mkdir()
        (self.out / "release.json").symlink_to(self.root / "cartridge.json")
        original = (self.root / "cartridge.json").read_bytes()
        with self.assertRaises(ValueError):
            packager.build(self.root, self.out, self.tag)
        self.assertEqual(original, (self.root / "cartridge.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
