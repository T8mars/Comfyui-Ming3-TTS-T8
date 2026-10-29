import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from ming_t8.updates import is_program_path
from scripts import build_program_release as builder


def program_sources(tmp_path, monkeypatch):
    root, component_source = tmp_path / "source", tmp_path / "components"
    root.mkdir()
    tracked = ["studio.py", "启动工作台.cmd", "一键更新.cmd", "scripts/update_program.py", "ming_t8/updates.py",
               "pyproject.toml", "components/component-manifest.json", "studio/app.js", "tests/ignored.py",
               "native/ignored.cu", ".github/workflows/ignored.yml", "settings.local.json", "data/private.txt"]
    for name in tracked:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"@echo off\necho program\n" if name.endswith(".cmd") else b"program" if is_program_path(name) else b"private")
    native_path = "components/cuda/ming_cuda.dll"
    native = component_source / native_path
    native.parent.mkdir(parents=True)
    native.write_bytes(b"native component")
    descriptor = {"path": native_path, "size": native.stat().st_size, "sha256": builder.sha256(native)}
    (root / "components/component-manifest.json").write_text(json.dumps({"files": [descriptor]}), encoding="utf-8")
    monkeypatch.setattr(builder.subprocess, "check_output", lambda *args, **kwargs: b"\0".join(name.encode() for name in tracked) + b"\0")
    return root, component_source


def test_program_release_uses_verified_native_fallback_and_flat_exact_members(tmp_path, monkeypatch):
    root, native = program_sources(tmp_path, monkeypatch)
    report = builder.build_program(root, tmp_path / "release", native, is_program_path, "0.2.0")
    assert report["all_member_hashes_passed"] and not report["python_runtime_included"] and not report["models_included"]
    assert Path(report["archive"]).name == "Ming3-TTS-T8-Program.zip"
    with zipfile.ZipFile(report["archive"]) as archive:
        manifest = json.loads(archive.read("program-manifest.json"))
        assert manifest["kind"] == "ming-t8-program" and manifest["version"] == "0.2.0"
        names = {item["path"] for item in manifest["files"]}
        assert set(archive.namelist()) == names | {"program-manifest.json"}
        assert "scripts/update_program.py" in names and "components/cuda/ming_cuda.dll" in names
        assert "data/private.txt" not in names and "settings.local.json" not in names
        assert "tests/ignored.py" not in names and "native/ignored.cu" not in names
        assert archive.read("启动工作台.cmd") == b"@echo off\r\necho program\r\n"
        assert all(hashlib.sha256(archive.read(item["path"])).hexdigest() == item["sha256"] for item in manifest["files"])
    assert Path(report["archive"] + ".sha256").read_text().split()[0] == report["sha256"]


def test_program_release_rejects_corrupt_component_before_creating_output(tmp_path, monkeypatch):
    root, native = program_sources(tmp_path, monkeypatch)
    (native / "components/cuda/ming_cuda.dll").write_bytes(b"tampered")
    output = tmp_path / "release"
    with pytest.raises(ValueError, match="checksum-matching"):
        builder.build_program(root, output, native, is_program_path, "0.2.0")
    assert not output.exists()


@pytest.mark.parametrize("name", ["components/ffmpeg/python.exe", "components/cuda/python312.dll", "assets/model.safetensors"])
def test_program_release_independently_rejects_runtime_and_model_payloads(name):
    with pytest.raises(ValueError, match="forbidden"):
        builder.check_program_asset(name, lambda value: True)
