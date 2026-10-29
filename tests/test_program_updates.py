from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import threading
import zipfile

import pytest

from ming_t8 import updates


def manifest(version, files):
    return {"schema": 1, "kind": "ming-t8-program", "version": version, "files": [
        {"path": name, "size": len(value), "sha256": hashlib.sha256(value).hexdigest()} for name, value in files.items()]}


def package(version="0.2.1", files=None):
    files = files or {"studio.py": b"new program"}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("program-manifest.json", json.dumps(manifest(version, files)))
        for name, value in files.items():
            archive.writestr(name, value)
    return buffer.getvalue()


def installed(root):
    (root / "studio.py").write_bytes(b"old program")
    updates.write_json(root / "program-manifest.json", manifest("0.2.0", {"studio.py": b"old program"}))


def stage(root, payload):
    archive = root / "test.zip"
    archive.write_bytes(payload)
    updates.Updates(root).stage_archive(archive, "0.2.1")


@pytest.mark.parametrize("name", ["runtime/python.exe", "python_embeded/python.exe", "data/models/a.gguf", "components/confucius/models/a.gguf",
    "ming_t8/models/campplus.onnx", "settings.local.json", "ming_t8/../../studio.py", "C:/studio.py", "ming_t8\\a.py", ".updates/pending.json", "studio/NUL.txt"])
def test_program_manifest_rejects_environment_models_and_unsafe_paths(name):
    assert not updates.is_program_path(name)
    with pytest.raises(updates.UpdateError):
        updates.validate_manifest(manifest("0.2.1", {name: b"no"}))


def test_stage_and_apply_preserves_runtime_models_and_user_data(tmp_path):
    installed(tmp_path)
    sentinels = {"runtime/python.exe": b"python", "data/models/model.safetensors": b"weights", "settings.local.json": b"settings",
                 "data/state/studio.sqlite3": b"database", "components/confucius/models/asr.gguf": b"asr"}
    for name, value in sentinels.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
    stage(tmp_path, package())
    assert (tmp_path / "studio.py").read_bytes() == b"old program"
    assert updates.apply_pending(tmp_path)
    assert (tmp_path / "studio.py").read_bytes() == b"new program"
    assert updates.current_version(tmp_path) == "0.2.1"
    assert not (tmp_path / ".updates/pending.json").exists()
    assert {name: (tmp_path / name).read_bytes() for name in sentinels} == sentinels
    assert not updates.apply_pending(tmp_path)


def test_update_does_not_apply_while_studio_owns_native_files(tmp_path):
    installed(tmp_path)
    stage(tmp_path, package())
    with updates.studio_lock(tmp_path), ThreadPoolExecutor(1) as pool:
        with pytest.raises(updates.UpdateError, match="仍在运行"):
            pool.submit(updates.apply_pending, tmp_path).result(timeout=5)
    assert (tmp_path / "studio.py").read_bytes() == b"old program"


def test_tampered_staged_content_never_changes_installed_program(tmp_path):
    installed(tmp_path)
    stage(tmp_path, package())
    pending = json.loads((tmp_path / ".updates/pending.json").read_text())
    (tmp_path / ".updates/staged" / pending["stage"] / "studio.py").write_bytes(b"tampered")
    with pytest.raises(updates.UpdateError, match="损坏"):
        updates.apply_pending(tmp_path)
    assert (tmp_path / "studio.py").read_bytes() == b"old program"


def test_apply_failure_rolls_back_every_program_file(tmp_path, monkeypatch):
    installed(tmp_path)
    stage(tmp_path, package(files={"studio.py": b"new program", "ming_t8/new.py": b"new module"}))
    original = updates.atomic_bytes
    failed = False

    def fail_once(path, content):
        nonlocal failed
        if Path(path) == tmp_path / "ming_t8/new.py" and not failed:
            failed = True
            raise PermissionError("simulated locked DLL")
        return original(path, content)

    monkeypatch.setattr(updates, "atomic_bytes", fail_once)
    with pytest.raises(updates.UpdateError, match="已恢复"):
        updates.apply_pending(tmp_path)
    assert updates.current_version(tmp_path) == "0.2.0"
    assert (tmp_path / "studio.py").read_bytes() == b"old program"
    assert not (tmp_path / "ming_t8/new.py").exists()
    assert (tmp_path / ".updates/pending.json").exists()
    assert updates.apply_pending(tmp_path)


def test_restart_recovers_journal_from_interrupted_install(tmp_path):
    installed(tmp_path)
    token = "a" * 32
    backup = tmp_path / ".updates/backups" / token
    backup.mkdir(parents=True)
    (backup / "studio.py").write_bytes(b"old program")
    updates.write_json(tmp_path / ".updates/journal.json", {"phase": "applying", "backup": token, "files": [
        {"path": "studio.py", "existed": True, "sha256": hashlib.sha256(b"old program").hexdigest()}]})
    (tmp_path / "studio.py").write_bytes(b"interrupted program")
    assert not updates.apply_pending(tmp_path)
    assert (tmp_path / "studio.py").read_bytes() == b"old program"


@pytest.mark.parametrize("change", ["hash", "extra", "duplicate", "protected"])
def test_corrupted_or_extra_archive_contents_never_become_pending(tmp_path, change):
    installed(tmp_path)
    content = package()
    source = zipfile.ZipFile(io.BytesIO(content))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as output:
        for name in source.namelist():
            value = source.read(name)
            output.writestr(name, b"corrupt" if change == "hash" and name == "studio.py" else value)
        if change == "extra": output.writestr("unlisted.py", b"extra")
        if change == "duplicate": output.writestr("Studio.py", b"collision")
        if change == "protected": output.writestr("runtime/python.exe", b"no")
    with pytest.raises(updates.UpdateError):
        stage(tmp_path, buffer.getvalue())
    assert not (tmp_path / ".updates/pending.json").exists()
    assert (tmp_path / "studio.py").read_bytes() == b"old program"


def fake_release(payload, **changes):
    value = {"tag_name": "v0.2.1", "draft": False, "prerelease": False, "assets": [{"name": updates.ASSET_NAME,
        "size": len(payload), "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "browser_download_url": f"https://github.com/{updates.REPOSITORY}/releases/download/v0.2.1/{updates.ASSET_NAME}"}]}
    value.update(changes)
    return value


def test_official_release_download_is_verified_and_staged(tmp_path):
    installed(tmp_path)
    payload = package()
    calls = []

    def opener(request, **kwargs):
        calls.append(request.full_url)
        return io.BytesIO(json.dumps(fake_release(payload)).encode() if request.full_url.endswith("/latest") else payload)

    manager = updates.Updates(tmp_path, opener)
    manager.start(download=True)
    manager.worker.join(timeout=5)
    assert manager.status()["status"] == "ready"
    assert len(calls) == 2
    assert (tmp_path / "studio.py").read_bytes() == b"old program"
    assert updates.apply_pending(tmp_path)


def test_offline_check_and_disabled_automatic_updates_do_not_break_studio(tmp_path):
    installed(tmp_path)
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(True)
        raise OSError("offline")

    manager = updates.Updates(tmp_path, unavailable)
    manager.set_automatic(False)
    manager.start(automatic=True)
    assert calls == []
    manager.start()
    manager.worker.join(timeout=5)
    assert manager.status()["status"] == "failed"
    assert (tmp_path / "studio.py").read_bytes() == b"old program"


def test_damaged_update_metadata_does_not_disable_local_studio(tmp_path):
    installed(tmp_path)
    preferences = tmp_path / ".updates/preferences.json"
    preferences.parent.mkdir()
    preferences.write_text("damaged")
    manager = updates.Updates(tmp_path)
    assert manager.status()["automatic"] is False
    (tmp_path / "program-manifest.json").write_text("damaged")
    assert manager.status()["managed"] is False
    assert manager.status()["status"] == "failed"


def test_actual_pinned_native_components_are_allowed_program_paths():
    source = Path(__file__).resolve().parents[1] / "components/component-manifest.json"
    descriptor = json.loads(source.read_text(encoding="utf-8"))
    for item in descriptor["files"]:
        assert updates.is_program_path(item["path"]), item["path"]


def test_persistent_locked_unchanged_dll_does_not_prevent_other_file_rollback(tmp_path, monkeypatch):
    installed(tmp_path)
    initial = tmp_path / "__init__.py"
    initial.write_bytes(b"old init")
    locked = tmp_path / "components/cuda/ming_cuda.dll"
    locked.parent.mkdir(parents=True)
    locked.write_bytes(b"old DLL")
    stage(tmp_path, package(files={"__init__.py": b"new init", "components/cuda/ming_cuda.dll": b"new DLL", "studio.py": b"new program"}))
    original = updates.atomic_bytes

    def persistent_lock(path, content):
        if Path(path) == locked:
            raise PermissionError("DLL remains loaded by another process")
        return original(path, content)

    monkeypatch.setattr(updates, "atomic_bytes", persistent_lock)
    with pytest.raises(updates.UpdateError, match="已恢复"):
        updates.apply_pending(tmp_path)
    assert initial.read_bytes() == b"old init"
    assert locked.read_bytes() == b"old DLL"
    assert (tmp_path / "studio.py").read_bytes() == b"old program"
