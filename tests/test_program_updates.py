from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
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


@pytest.mark.skipif(os.name != "nt", reason="Case-only renames use Windows filesystem semantics")
def test_windows_case_only_program_rename_can_be_updated(tmp_path):
    installed(tmp_path)
    (tmp_path / "studio").mkdir()
    (tmp_path / "studio/Voice.js").write_bytes(b"old script")
    updates.write_json(tmp_path / "program-manifest.json", manifest("0.2.0", {
        "studio.py": b"old program", "studio/Voice.js": b"old script"}))
    stage(tmp_path, package(files={"studio.py": b"new program", "studio/voice.js": b"new script"}))
    assert updates.apply_pending(tmp_path)
    assert (tmp_path / "studio/voice.js").read_bytes() == b"new script"
    assert updates.current_version(tmp_path) == "0.2.1"


@pytest.mark.parametrize("damage", ["pending_json", "stage_missing", "stage_hash"])
def test_launcher_can_use_intact_program_when_pending_update_is_unusable(tmp_path, damage):
    installed(tmp_path)
    source = Path(__file__).resolve().parents[1]
    (tmp_path / "scripts").mkdir()
    (tmp_path / "ming_t8").mkdir()
    for name in ("scripts/update_program.py", "ming_t8/updates.py", "ming_t8/__init__.py"):
        shutil.copyfile(source / name, tmp_path / name)
    if damage == "pending_json":
        updates.atomic_bytes(tmp_path / ".updates/pending.json", b"{broken")
    elif damage == "stage_missing":
        updates.write_json(tmp_path / ".updates/pending.json", {"stage": "a" * 32, "version": "0.2.1"})
    else:
        stage(tmp_path, package())
        pending = json.loads((tmp_path / ".updates/pending.json").read_text())
        (tmp_path / ".updates/staged" / pending["stage"] / "studio.py").write_bytes(b"bad")
    result = subprocess.run([sys.executable, "-X", "utf8", str(tmp_path / "scripts/update_program.py"), "--apply-pending"],
                            capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert (tmp_path / "studio.py").read_bytes() == b"old program"
    assert not (tmp_path / ".updates/pending.json").exists()
    assert list((tmp_path / ".updates").glob("rejected-pending-*.json"))


def test_failed_journal_recovery_is_never_treated_as_safe_to_launch(tmp_path):
    installed(tmp_path)
    (tmp_path / "studio.py").write_bytes(b"interrupted program")
    updates.write_json(tmp_path / ".updates/journal.json", {"phase": "applying", "backup": "a" * 32, "files": [
        {"path": "studio.py", "existed": True, "sha256": hashlib.sha256(b"old program").hexdigest()}]})
    updates.atomic_bytes(tmp_path / ".updates/pending.json", b"{broken")
    with pytest.raises(Exception) as captured:
        updates.apply_pending(tmp_path)
    assert not isinstance(captured.value, updates.UpdateRolledBack)
    assert (tmp_path / ".updates/journal.json").exists()
    assert (tmp_path / ".updates/pending.json").exists()
    assert (tmp_path / "studio.py").read_bytes() == b"interrupted program"


def test_unusable_pending_cannot_hide_a_damaged_installed_program(tmp_path):
    installed(tmp_path)
    (tmp_path / "studio.py").write_bytes(b"damaged old program")
    updates.atomic_bytes(tmp_path / ".updates/pending.json", b"{broken")
    with pytest.raises(updates.UpdateError) as captured:
        updates.apply_pending(tmp_path)
    assert not isinstance(captured.value, updates.UpdateRolledBack)
    assert (tmp_path / ".updates/pending.json").exists()
    assert not list((tmp_path / ".updates").glob("rejected-pending-*.json"))


@pytest.mark.skipif(os.name != "nt", reason="The release targets Windows junction handling")
def test_case_tolerant_program_paths_still_reject_real_directory_junctions(tmp_path):
    destination = tmp_path / "assets"
    destination.mkdir()
    (destination / "linked.js").write_bytes(b"script")
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(tmp_path / "studio"), str(destination)],
                            capture_output=True, timeout=5)
    assert result.returncode == 0
    with pytest.raises(updates.UpdateError, match="符号链接"):
        updates.program_path(tmp_path, "studio/linked.js")


def test_repeated_successful_updates_bound_owned_cache_and_keep_unknown_directories(tmp_path):
    installed(tmp_path)
    unknown = tmp_path / ".updates/staged" / ("f" * 32)
    unknown.mkdir(parents=True)
    (unknown / "personal.txt").write_bytes(b"leave unknown directory")
    legacy = tmp_path / ".updates/staged" / ("e" * 32)
    legacy.mkdir()
    (legacy / "studio.py").write_bytes(b"legacy cached program")
    updates.write_json(legacy / "program-manifest.json", manifest("0.1.9", {"studio.py": b"legacy cached program"}))
    for number in range(1, 4):
        version = f"0.2.{number}"
        archive = tmp_path / "fixture.zip"
        archive.write_bytes(package(version, {"studio.py": f"program-{number}".encode(),
                                               "components/cuda/fixture.dll": bytes([number]) * 1024**2}))
        updates.Updates(tmp_path).stage_archive(archive, version)
        assert updates.apply_pending(tmp_path)
        assert sorted(path.name for path in (tmp_path / ".updates/staged").iterdir()) == ["f" * 32]
        assert len(list((tmp_path / ".updates/backups").iterdir())) == 1
        assert (unknown / "personal.txt").read_bytes() == b"leave unknown directory"


def test_failed_stage_removes_only_its_own_partial_directory(tmp_path):
    installed(tmp_path)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("program-manifest.json", json.dumps(manifest("0.2.1", {"studio.py": b"valid", "ming_t8/bad.py": b"expected"})))
        archive.writestr("studio.py", b"valid")
        archive.writestr("ming_t8/bad.py", b"tampered")
    with pytest.raises(updates.UpdateError):
        stage(tmp_path, buffer.getvalue())
    staged = tmp_path / ".updates/staged"
    assert not staged.exists() or not list(staged.iterdir())
    assert (tmp_path / "studio.py").read_bytes() == b"old program"


def test_cache_cleanup_failure_does_not_undo_a_committed_update(tmp_path, monkeypatch):
    installed(tmp_path)
    stage(tmp_path, package())
    real_rmtree = updates.shutil.rmtree

    def locked_cache(*args, **kwargs):
        raise PermissionError("temporary cache lock")

    monkeypatch.setattr(updates.shutil, "rmtree", locked_cache)
    assert updates.apply_pending(tmp_path)
    assert updates.current_version(tmp_path) == "0.2.1"
    assert (tmp_path / "studio.py").read_bytes() == b"new program"
    assert not (tmp_path / ".updates/pending.json").exists()
    assert not (tmp_path / ".updates/journal.json").exists()
    assert (tmp_path / ".updates/cleanup-warning.json").exists()
    monkeypatch.setattr(updates.shutil, "rmtree", real_rmtree)


def test_cache_cleanup_preserves_pending_and_journal_dependencies(tmp_path):
    installed(tmp_path)
    stage(tmp_path, package())
    pending = json.loads((tmp_path / ".updates/pending.json").read_text())
    backup_token = "a" * 32
    updates._mark_transaction(tmp_path, "backups", backup_token)
    backup = tmp_path / ".updates/backups" / backup_token
    shutil.copyfile(tmp_path / "studio.py", backup / "studio.py")
    shutil.copyfile(tmp_path / "program-manifest.json", backup / "program-manifest.json")
    updates.write_json(tmp_path / ".updates/journal.json", {"phase": "applying", "backup": backup_token, "files": []})
    updates._cleanup_transactions(tmp_path, keep_backup="b" * 32)
    assert (tmp_path / ".updates/staged" / pending["stage"] / "studio.py").exists()
    assert (backup / "studio.py").read_bytes() == b"old program"


@pytest.mark.skipif(os.name != "nt", reason="The release targets Windows junction handling")
def test_cache_cleanup_never_deletes_through_a_directory_junction(tmp_path):
    installed(tmp_path)
    user_directory = tmp_path / "data/models/user-directory"
    user_directory.mkdir(parents=True)
    (user_directory / "studio.py").write_bytes(b"user file")
    updates.write_json(user_directory / "program-manifest.json", manifest("0.1.9", {"studio.py": b"user file"}))
    staged = tmp_path / ".updates/staged"
    staged.mkdir(parents=True)
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(staged / ("c" * 32)), str(user_directory)],
                            capture_output=True, timeout=5)
    assert result.returncode == 0
    updates._cleanup_transactions(tmp_path)
    assert (user_directory / "studio.py").read_bytes() == b"user file"
    assert (staged / ("c" * 32)).is_dir()


def test_no_pending_start_cleans_legacy_caches_and_keeps_latest_owned_backup(tmp_path):
    installed(tmp_path)
    for category, tokens in (("staged", ["a" * 32, "b" * 32]), ("backups", ["c" * 32, "d" * 32])):
        for token in tokens:
            directory = tmp_path / ".updates" / category / token
            directory.mkdir(parents=True)
            (directory / "studio.py").write_bytes(b"old program")
            updates.write_json(directory / "program-manifest.json", manifest("0.2.0", {"studio.py": b"old program"}))
    older = tmp_path / ".updates/backups" / ("c" * 32)
    latest = tmp_path / ".updates/backups" / ("d" * 32)
    os.utime(older, ns=(1000000000, 1000000000))
    os.utime(latest, ns=(2000000000, 2000000000))
    unknown = tmp_path / ".updates/backups" / ("f" * 32)
    unknown.mkdir()
    (unknown / "personal.txt").write_bytes(b"leave unknown backup")
    assert not updates.apply_pending(tmp_path)
    assert not list((tmp_path / ".updates/staged").iterdir())
    assert latest.is_dir() and not older.exists()
    assert (unknown / "personal.txt").read_bytes() == b"leave unknown backup"


@pytest.mark.parametrize("direction", ["directory_to_file", "file_to_directory"])
def test_layout_conflicts_are_rejected_before_any_program_mutation(tmp_path, direction):
    old = {"studio.py": b"old program", **({"studio/resource/child.js": b"old child"} if direction == "directory_to_file" else {"studio/resource": b"old resource"})}
    new = {"studio.py": b"new program", **({"studio/resource": b"new resource"} if direction == "directory_to_file" else {"studio/resource/child.js": b"new child"})}
    for name, value in old.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
    updates.write_json(tmp_path / "program-manifest.json", manifest("0.2.0", old))
    before = (tmp_path / "program-manifest.json").read_bytes()
    stage(tmp_path, package(files=new))
    with pytest.raises(updates.UpdateRolledBack, match="独立目录"):
        updates.apply_pending(tmp_path)
    assert {name: (tmp_path / name).read_bytes() for name in old} == old
    assert (tmp_path / "program-manifest.json").read_bytes() == before
    assert not (tmp_path / ".updates/journal.json").exists()
    assert not (tmp_path / ".updates/pending.json").exists()


@pytest.mark.parametrize("direction", ["directory_to_file", "file_to_directory"])
def test_launcher_starts_the_intact_old_program_after_layout_conflict(tmp_path, direction):
    source = Path(__file__).resolve().parents[1]
    installed(tmp_path)
    for name in ("scripts/update_program.py", "ming_t8/updates.py", "ming_t8/__init__.py"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    if direction == "directory_to_file":
        (tmp_path / "studio/resource").mkdir(parents=True)
        (tmp_path / "studio/resource/child.js").write_bytes(b"old child")
        old_extra, new_extra = {"studio/resource/child.js": b"old child"}, {"studio/resource": b"new resource"}
    else:
        (tmp_path / "studio").mkdir()
        (tmp_path / "studio/resource").write_bytes(b"old resource")
        old_extra, new_extra = {"studio/resource": b"old resource"}, {"studio/resource/child.js": b"new child"}
    updates.write_json(tmp_path / "program-manifest.json", manifest("0.2.0", {"studio.py": b"old program", **old_extra}))
    stage(tmp_path, package(files={"studio.py": b"new program", **new_extra}))
    result = subprocess.run([sys.executable, "-X", "utf8", str(tmp_path / "scripts/update_program.py"), "--apply-pending"],
                            capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "独立目录" in result.stdout
    assert (tmp_path / "studio.py").read_bytes() == b"old program"


@pytest.mark.parametrize("failure", ["copy", "journal"])
def test_preparation_failure_keeps_old_program_launchable_and_pending_for_retry(tmp_path, monkeypatch, failure):
    installed(tmp_path)
    stage(tmp_path, package())
    before = (tmp_path / "program-manifest.json").read_bytes()
    if failure == "copy":
        monkeypatch.setattr(updates.shutil, "copyfile", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    else:
        original = updates.write_json

        def fail_journal(path, value):
            if Path(path).name == "journal.json":
                raise OSError("disk full writing journal")
            return original(path, value)

        monkeypatch.setattr(updates, "write_json", fail_journal)
    with pytest.raises(updates.UpdateRolledBack, match="准备"):
        updates.apply_pending(tmp_path)
    assert (tmp_path / "studio.py").read_bytes() == b"old program"
    assert (tmp_path / "program-manifest.json").read_bytes() == before
    assert (tmp_path / ".updates/pending.json").exists()
    assert not (tmp_path / ".updates/journal.json").exists()


@pytest.mark.parametrize("locked_name", ["pending.json", "journal.json"])
def test_committed_metadata_cleanup_failure_does_not_block_or_reinstall(tmp_path, monkeypatch, locked_name):
    installed(tmp_path)
    stage(tmp_path, package())
    original = Path.unlink

    def locked_record(path, *args, **kwargs):
        if path == tmp_path / ".updates" / locked_name:
            raise PermissionError("metadata held by antivirus")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_record)
    assert updates.apply_pending(tmp_path)
    assert updates.current_version(tmp_path) == "0.2.1"
    assert (tmp_path / "studio.py").read_bytes() == b"new program"
    backups = {path.name for path in (tmp_path / ".updates/backups").iterdir()}
    assert not updates.apply_pending(tmp_path)
    assert {path.name for path in (tmp_path / ".updates/backups").iterdir()} == backups
    state = updates.Updates(tmp_path).status()
    assert state["status"] != "ready"
    if locked_name == "pending.json":
        assert "已更新" in state["message"]
    monkeypatch.setattr(Path, "unlink", original)
    assert not updates.apply_pending(tmp_path)
    assert not (tmp_path / ".updates/pending.json").exists()
    assert not (tmp_path / ".updates/journal.json").exists()


def test_committed_journal_cannot_hide_corrupt_installed_files(tmp_path):
    installed(tmp_path)
    (tmp_path / "studio.py").write_bytes(b"broken installed program")
    updates.write_json(tmp_path / ".updates/journal.json", {"phase": "committed", "backup": "a" * 32, "files": []})
    with pytest.raises(updates.UpdateError):
        updates.apply_pending(tmp_path)
    assert (tmp_path / ".updates/journal.json").exists()


def test_committed_cleanup_preserves_a_newer_pending_transaction(tmp_path, monkeypatch):
    installed(tmp_path)
    future_archive = tmp_path / "future.zip"
    future_archive.write_bytes(package("0.2.2", {"studio.py": b"future program"}))
    updates.Updates(tmp_path).stage_archive(future_archive, "0.2.2")
    future = json.loads((tmp_path / ".updates/pending.json").read_text(encoding="utf-8"))
    stage(tmp_path, package())
    original = updates.write_json

    def publish_future_after_commit(path, value):
        original(path, value)
        if Path(path).name == "journal.json" and value.get("phase") == "committed":
            original(tmp_path / ".updates/pending.json", future)

    monkeypatch.setattr(updates, "write_json", publish_future_after_commit)
    assert updates.apply_pending(tmp_path)
    assert updates.current_version(tmp_path) == "0.2.1"
    assert json.loads((tmp_path / ".updates/pending.json").read_text(encoding="utf-8")) == future
    assert (tmp_path / ".updates/staged" / future["stage"] / "studio.py").read_bytes() == b"future program"
    assert updates.Updates(tmp_path).status()["status"] == "ready"


def test_preparation_failure_cannot_hide_a_damaged_old_program(tmp_path, monkeypatch):
    installed(tmp_path)
    stage(tmp_path, package())
    (tmp_path / "studio.py").write_bytes(b"damaged old program")
    monkeypatch.setattr(updates.shutil, "copyfile", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(updates.UpdateError) as captured:
        updates.apply_pending(tmp_path)
    assert not isinstance(captured.value, updates.UpdateRolledBack)
    assert (tmp_path / ".updates/pending.json").exists()


def test_rollback_metadata_lock_keeps_the_verified_old_program_launchable(tmp_path, monkeypatch):
    installed(tmp_path)
    stage(tmp_path, package(files={"studio.py": b"new program", "ming_t8/new.py": b"new module"}))
    atomic, unlink = updates.atomic_bytes, Path.unlink
    failed = False

    def fail_once(path, value):
        nonlocal failed
        if Path(path) == tmp_path / "ming_t8/new.py" and not failed:
            failed = True
            raise PermissionError("simulated locked program component")
        return atomic(path, value)

    def lock_journal(path, *args, **kwargs):
        if path == tmp_path / ".updates/journal.json":
            raise PermissionError("journal held by antivirus")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(updates, "atomic_bytes", fail_once)
    monkeypatch.setattr(Path, "unlink", lock_journal)
    with pytest.raises(updates.UpdateRolledBack):
        updates.apply_pending(tmp_path)
    assert (tmp_path / "studio.py").read_bytes() == b"old program"
    journal = json.loads((tmp_path / ".updates/journal.json").read_text(encoding="utf-8"))
    assert (tmp_path / ".updates/backups" / journal["backup"]).exists()
    assert not updates.apply_pending(tmp_path)
    monkeypatch.setattr(Path, "unlink", unlink)
    assert updates.apply_pending(tmp_path)
    assert (tmp_path / "studio.py").read_bytes() == b"new program"
