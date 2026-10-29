"""Build a verified flat program ZIP without Python, models or user files."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_NAME = "Ming3-TTS-T8-Program.zip"
MANIFEST_NAME = "program-manifest.json"
MODEL_SUFFIXES = {".safetensors", ".gguf", ".onnx", ".pt", ".pth", ".ckpt", ".bin", ".tflite", ".h5"}


def sha256(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            checksum.update(block)
    return checksum.hexdigest()


def safe_relative(value):
    if not isinstance(value, str) or "\\" in value or ":" in value:
        raise ValueError(f"Invalid program path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value or value in ("", "."):
        raise ValueError(f"Invalid program path: {value!r}")
    return path.as_posix()


def check_program_asset(name, allowed):
    name = safe_relative(name)
    path = PurePosixPath(name)
    leaf = path.name.lower()
    if (not allowed(name) or path.suffix.lower() in MODEL_SUFFIXES
            or re.fullmatch(r"python(?:w|\d+)?(?:_d)?\.(?:exe|dll|zip)", leaf)
            or path.parts[0] in {"tests", "native", ".github"}):
        raise ValueError(f"Interpreter, model or non-program file is forbidden: {name}")
    return name


def source_file(root, name):
    root = Path(root).resolve(strict=True)
    path = root / name
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError(f"Missing or unsafe source file: {path}")
    return path


def collect_sources(root, component_source, allowed):
    root = Path(root).resolve(strict=True)
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).split(b"\0")
    sources = {}
    for raw in tracked:
        if not raw:
            continue
        name = raw.decode("utf-8")
        if name.startswith(("tests/", "native/", ".github/")) or not allowed(name):
            continue
        check_program_asset(name, allowed)
        sources[name] = source_file(root, name)
    component_manifest = root / "components/component-manifest.json"
    components = json.loads(component_manifest.read_text(encoding="utf-8"))
    for item in components["files"]:
        name = check_program_asset(item["path"], allowed)
        if not name.startswith(("components/", "licenses/")):
            raise ValueError(f"Unexpected component destination: {name}")
        if type(item.get("size")) is not int or item["size"] < 0 or not re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", "")):
            raise ValueError(f"Invalid component checksum descriptor: {name}")
        candidates = [root]
        if component_source is not None:
            candidates.append(Path(component_source))
        source = None
        for candidate in candidates:
            if not (candidate / name).is_file():
                continue
            current = source_file(candidate, name)
            if current.stat().st_size == item["size"] and sha256(current) == item["sha256"]:
                source = current
                break
        if source is None:
            raise ValueError(f"No checksum-matching native component found: {name}; use --components-from with a complete bundle")
        sources[name] = source
    required = {"studio.py", "启动工作台.cmd", "一键更新.cmd", "scripts/update_program.py", "ming_t8/updates.py",
                "pyproject.toml", "components/component-manifest.json"}
    missing = required - sources.keys()
    if missing:
        raise ValueError("Required program files are absent from git ls-files; stage the new product files first: " + ", ".join(sorted(missing)))
    if len({name.casefold() for name in sources}) != len(sources):
        raise ValueError("Program paths collide on Windows")
    return sources


def atomic_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=target.name + ".build-", dir=target.parent)
    os.close(descriptor)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_write(target, content):
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=target.name + ".build-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def verify_archive(archive, manifest, allowed, manifest_bytes):
    expected = {item["path"]: item for item in manifest["files"]}
    with zipfile.ZipFile(archive) as stored:
        members = stored.namelist()
        if len(members) != len(expected) + 1 or set(members) != set(expected) | {MANIFEST_NAME}:
            raise ValueError("Program ZIP must have exactly the flat manifest-owned files")
        if stored.read(MANIFEST_NAME) != manifest_bytes:
            raise ValueError("Archived manifest differs from the program directory")
        for name, item in expected.items():
            check_program_asset(name, allowed)
            if stored.getinfo(name).file_size != item["size"]:
                raise ValueError(f"Archived size mismatch: {name}")
            checksum = hashlib.sha256()
            with stored.open(name) as stream:
                for block in iter(lambda: stream.read(8 * 1024**2), b""):
                    checksum.update(block)
            if checksum.hexdigest() != item["sha256"]:
                raise ValueError(f"Archived SHA256 mismatch: {name}")


def build_program(root, output, component_source, allowed, version, refresh=False):
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Program version must use major.minor.patch")
    sources = collect_sources(root, component_source, allowed)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    folder = output / f"Program-{version}"
    if folder.is_symlink():
        raise ValueError("Program output cannot be a symlink")
    if folder.exists():
        if not refresh or not (folder / MANIFEST_NAME).is_file():
            raise ValueError("Program output already exists; --refresh requires a previous program-manifest.json")
        previous = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
        if previous.get("schema") != 1 or previous.get("kind") != "ming-t8-program" or previous.get("version") != version:
            raise ValueError("Output is not this program version's managed directory")
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for name, source in sorted(sources.items()):
        target = folder / name
        if not target.resolve().is_relative_to(folder.resolve()):
            raise ValueError(f"Output path escapes program directory: {name}")
        if target.suffix.lower() == ".cmd":
            atomic_write(target, source.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        else:
            atomic_copy(source, target)
        files.append({"path": name, "size": target.stat().st_size, "sha256": sha256(target)})
    manifest = {"schema": 1, "kind": "ming-t8-program", "version": version, "files": files}
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    atomic_write(folder / MANIFEST_NAME, manifest_bytes)
    archive = output / ARCHIVE_NAME
    descriptor, temporary = tempfile.mkstemp(prefix=archive.name + ".", suffix=".part", dir=output)
    os.close(descriptor)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True) as stored:
            for item in files:
                stored.write(folder / item["path"], item["path"])
            stored.writestr(MANIFEST_NAME, manifest_bytes)
        verify_archive(temporary, manifest, allowed, manifest_bytes)
        os.replace(temporary, archive)
    finally:
        Path(temporary).unlink(missing_ok=True)
    checksum = sha256(archive)
    atomic_write(archive.with_suffix(".zip.sha256"), f"{checksum}  {archive.name}\n".encode("ascii"))
    return {"version": version, "folder": str(folder), "archive": str(archive), "files": len(files),
            "bytes": archive.stat().st_size, "sha256": checksum, "all_member_hashes_passed": True,
            "python_runtime_included": False, "models_included": False, "user_data_included": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--components-from", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from ming_t8.updates import VERSION, is_program_path
    report = build_program(ROOT, args.output, args.components_from, is_program_path, VERSION, args.refresh)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
