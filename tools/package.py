#!/usr/bin/env python3
"""Validate and build a reproducible Cartridge release using only Python's stdlib."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile

APP_ID = "dev.cartridge.frequency"
REPOSITORY = "Strizzo/frequency-cartridge"
MIN_RUNTIME = "0.6.2"
ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")


def safe_path(root, name):
    """Reject traversal, ambiguous names, links (including ancestors), and devices."""
    if not isinstance(name, str) or not name or len(name.encode()) > 100:
        raise ValueError(f"Invalid payload path: {name!r}")
    parts = name.split("/")
    if any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", p) for p in parts):
        raise ValueError(f"Unsafe payload path: {name!r}")
    path = root
    for i, part in enumerate(parts):
        path = path / part
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"Links are forbidden: {name}")
        if i < len(parts) - 1:
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError(f"Not a directory: {path}")
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError(f"Expected a regular file without hard links: {name}")
    return path


def read_json(root, name):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(safe_path(root, name).read_text(encoding="utf-8"), object_pairs_hook=unique)


def validate(root, tag=None):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Repository root must be a real directory")
    manifest = read_json(root, "cartridge.json")
    if not isinstance(manifest, dict) or manifest.get("id") != APP_ID:
        raise ValueError(f"Manifest id must be {APP_ID}")
    version = manifest.get("version")
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ValueError("Manifest version must be MAJOR.MINOR.PATCH without leading zeroes")
    if tag is not None and tag != f"v{version}":
        raise ValueError("Release tag must exactly match v + manifest version")
    if manifest.get("min_runtime") != MIN_RUNTIME:
        raise ValueError(f"min_runtime must be {MIN_RUNTIME}")
    if manifest.get("entry") != "main.lua" or manifest.get("icon") != "icon.png":
        raise ValueError("Expected entry main.lua and icon icon.png")
    permissions = manifest.get("permissions")
    if (not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions)
            or len(set(permissions)) != len(permissions)
            or not set(permissions) <= {"audio", "network", "storage"}):
        raise ValueError("Invalid or duplicate permissions")
    for field in ("name", "description", "author", "category"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ValueError(f"Missing manifest field: {field}")
    names = read_json(root, "package-files.json")
    if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
        raise ValueError("package-files.json must be a nonempty list of file paths")
    if len(names) != len(set(names)):
        raise ValueError("Duplicate payload paths")
    case_names = [n.casefold() for n in names]
    if len(case_names) != len(set(case_names)):
        raise ValueError("Case-colliding payload paths")
    payload = {}
    for name in names:
        path = safe_path(root, name)
        p = PurePosixPath(name)
        allowed = name in {"cartridge.json", "icon.png", "LICENSE"} or (
            len(p.parts) == 1 and p.suffix == ".lua"
        ) or (p.parts[0] == "assets" and p.suffix in {".png", ".svg", ".json", ".jpg", ".webp", ".wav", ".ogg"})
        if not allowed:
            raise ValueError(f"Development or unsupported file in payload: {name}")
        payload[name] = path.read_bytes()
    expected = {"main.lua", "cartridge.json", "icon.png", "LICENSE"}
    expected.update(p.name for p in root.glob("*.lua"))
    assets = root / "assets"
    if assets.is_symlink():
        raise ValueError("Links are forbidden: assets")
    if assets.exists():
        if not assets.is_dir():
            raise ValueError("assets must be a directory")
        for path in assets.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"Links are forbidden: {path}")
            if not path.is_dir():
                expected.add(path.relative_to(root).as_posix())
    if set(payload) != expected:
        raise ValueError(f"Payload inventory mismatch: missing={sorted(expected-set(payload))}, extra={sorted(set(payload)-expected)}")
    if not payload["icon.png"].startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Launcher icon must be PNG")
    if b"GNU GENERAL PUBLIC LICENSE" not in payload["LICENSE"] or b"Version 3, 29 June 2007" not in payload["LICENSE"]:
        raise ValueError("Expected GPL version 3 license")
    # Every literal local require and asset reference must resolve in the package.
    for name, data in payload.items():
        if name.endswith(".lua"):
            code = data.decode("utf-8")
            for module in re.findall(r"\brequire\s*\(?\s*['\"]([^'\"]+)['\"]", code):
                if module.replace(".", "/") + ".lua" not in payload:
                    raise ValueError(f"Missing Lua module: {module} (from {name})")
            for asset in re.findall(r"['\"](assets/[^'\"]+)['\"]", code):
                if "%d" in asset:
                    # Only numeric printf fields are allowed for baked tile names.
                    # Inventory validation still requires every generated asset.
                    pattern = re.escape(asset).replace("%d", r"[0-9]+")
                    present = any(re.fullmatch(pattern, path) for path in payload)
                else:
                    present = asset in payload
                if not present:
                    raise ValueError(f"Missing asset: {asset} (from {name})")
    return manifest, payload


def build(root, output, tag):
    manifest, payload = validate(root, tag)
    if tag is None:
        raise ValueError("A release tag is required when packaging")
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, data in sorted(payload.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            info.uid = info.gid = info.mtime = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(data))
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, filename="", mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(archive_bytes.getvalue())
    data = compressed.getvalue()
    filename = f"{APP_ID}.tar.gz"
    metadata = {
        "id": APP_ID, "version": manifest["version"],
        "url": f"https://github.com/{REPOSITORY}/releases/download/{tag}/{filename}",
        "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
        "min_runtime": manifest["min_runtime"], "permissions": manifest["permissions"],
    }
    release_bytes = (json.dumps(metadata, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    sums = (f"{metadata['sha256']}  {filename}\n"
            f"{hashlib.sha256(release_bytes).hexdigest()}  release.json\n").encode("ascii")
    output = Path(output)
    # Do not follow an existing symlink in any output component or overwrite input.
    for path in (output, *output.parents):
        if path.is_symlink():
            raise ValueError(f"Output path contains a link: {path}")
    if output.resolve() == Path(root).resolve():
        raise ValueError("Output directory must not be the repository root")
    output.mkdir(parents=True, exist_ok=True)
    products = {filename: data, "release.json": release_bytes, "SHA256SUMS": sums}
    for name in products:
        path = output / name
        if path.exists() or path.is_symlink():
            safe_path(output, name)
    for name, content in products.items():
        (output / name).write_bytes(content)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Required for packaging: v + manifest version")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--check", action="store_true", help="Only validate the source payload")
    args = parser.parse_args()
    try:
        if args.check:
            manifest, payload = validate(ROOT, args.tag)
            print(f"Validated {manifest['id']} {manifest['version']}: {len(payload)} runtime files")
        else:
            print(json.dumps(build(ROOT, args.output, args.tag), indent=2))
    except (ValueError, OSError, UnicodeError) as error:
        parser.exit(1, f"Package validation failed: {error}\n")


if __name__ == "__main__":
    main()
