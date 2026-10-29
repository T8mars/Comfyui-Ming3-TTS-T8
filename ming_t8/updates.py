"""Program-only GitHub updates, staged online and applied with the studio closed."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import threading
import urllib.parse
import urllib.request
import uuid
import zipfile

from filelock import FileLock, Timeout

VERSION = "0.2.0"
ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "T8mars/Comfyui-Ming3-TTS-T8"
ASSET_NAME = "Ming3-TTS-T8-Program.zip"
MAX_ARCHIVE = 512 * 1024**2
MAX_CONTENT = 1024**3
ROOT_FILES = {
    "__init__.py", "nodes.py", "studio.py", "install.py", "requirements.txt", "requirements-studio.txt",
    "settings.example.json", "pyproject.toml", "README.md", "README.en.md", "CHANGELOG.md", "LICENSE", "NOTICE",
    "THIRD_PARTY_NOTICES.md", "节点使用说明.md", "安装Comfy节点.ps1", "启动工作台.cmd", "一键更新.cmd", "使用说明.txt",
}


class UpdateError(ValueError):
    pass


class UpdateRolledBack(UpdateError):
    """The old program is intact and can still be launched safely."""


def version_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"v?\d+\.\d+\.\d+", value):
        raise UpdateError("不支持的程序版本号")
    return tuple(map(int, value.removeprefix("v").split(".")))


def is_program_path(relative):
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        return False
    path = PurePosixPath(relative)
    if path.is_absolute() or path.as_posix() != relative or any(part in ("", ".", "..") for part in path.parts):
        return False
    forbidden = {"runtime", "python_embeded", "python_embedded", "models", "data", "cache", "outputs", "state", ".git", ".updates", "__pycache__"}
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    for part in path.parts:
        if part.lower() == "python" and not relative.startswith("components/confucius/.runtime/"):
            return False
        if part.lower() in forbidden or part.endswith((".", " ")) or part.split(".")[0].upper() in reserved:
            return False
        if any(ord(character) < 32 for character in part):
            return False
    if path.suffix.lower() in (".safetensors", ".gguf", ".onnx", ".ark", ".bin", ".pt", ".pth", ".ckpt", ".tflite", ".h5", ".whl", ".pyc"):
        return False
    if path.name.lower() in {"python.exe", "pythonw.exe", "python3.exe"} or re.fullmatch(r"python\d*(?:_d)?\.dll", path.name.lower()):
        return False
    if any(part.lower().startswith("settings.local") for part in path.parts):
        return False
    if len(path.parts) == 1:
        return relative in ROOT_FILES
    if path.parts[0] in {"ming_t8", "studio", "web", "assets", "examples", "docs", "licenses", "scripts"}:
        return not any(part.startswith(".") for part in path.parts)
    if relative == "components/component-manifest.json":
        return True
    if relative.startswith(("components/cuda/", "components/ffmpeg/", "components/confucius/.runtime/")):
        return path.suffix.lower() in {".dll", ".pyd", ".py", ".json", ".txt", ".md"} or relative == "components/ffmpeg/ffmpeg.exe"
    return False


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            value.update(block)
    return value.hexdigest()


def atomic_bytes(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path, value):
    atomic_bytes(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


def program_path(root, relative):
    if relative != "program-manifest.json" and not is_program_path(relative):
        raise UpdateError(f"更新不允许修改此路径：{relative}")
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or target == root:
        raise UpdateError("更新路径超出程序目录")
    actual = target.relative_to(root).as_posix()
    if actual != relative:
        raise UpdateError("更新路径不能经过符号链接")
    return target


def validate_manifest(value, expected_version=None):
    if not isinstance(value, dict) or value.get("schema") != 1 or value.get("kind") != "ming-t8-program":
        raise UpdateError("这不是受支持的明语音程序更新包")
    version_key(value.get("version"))
    if expected_version and version_key(value["version"]) != version_key(expected_version):
        raise UpdateError("程序包版本与发布版本不一致")
    files = value.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 5000:
        raise UpdateError("程序文件清单无效")
    seen, total = set(), 0
    for item in files:
        if not isinstance(item, dict) or not is_program_path(item.get("path")):
            raise UpdateError("程序包包含运行环境、模型或无效路径")
        name = item["path"].casefold()
        if name in seen:
            raise UpdateError("程序包包含重复文件名")
        seen.add(name)
        if type(item.get("size")) is not int or not 0 <= item["size"] <= MAX_CONTENT:
            raise UpdateError("程序文件长度无效")
        if not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise UpdateError("程序文件校验信息无效")
        total += item["size"]
    if total > MAX_CONTENT:
        raise UpdateError("程序更新包解压后超过1GiB")
    return value


def current_version(root=ROOT):
    path = Path(root) / "program-manifest.json"
    if path.is_file():
        value = validate_manifest(json.loads(path.read_text(encoding="utf-8")))
        return value["version"]
    return VERSION


@contextmanager
def studio_lock(root=ROOT):
    path = Path(root) / ".updates/studio.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(path), timeout=0):
            yield
    except Timeout as error:
        raise UpdateError("工作台仍在运行，请先关闭工作台窗口后再安装更新") from error


def _owned_directory(root, category, token):
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise UpdateError("更新事务目录无效")
    root = Path(root).resolve()
    base = (root / ".updates" / category).resolve()
    if not base.is_relative_to(root / ".updates"):
        raise UpdateError("更新事务目录不能经过符号链接")
    result = (base / token).resolve()
    if result.parent != base:
        raise UpdateError("更新事务目录超出范围")
    return result


def _rollback(root, journal):
    backup = _owned_directory(root, "backups", journal["backup"])
    for item in journal["files"]:
        path = program_path(root, item["path"])
        if item["existed"] and digest(program_path(backup, item["path"])) != item["sha256"]:
            raise UpdateError("更新备份校验失败，已停止操作，请保留.updates目录")
    for item in reversed(journal["files"]):
        path = program_path(root, item["path"])
        if item["existed"]:
            # A locked DLL whose replacement failed may already be the original.
            if not path.is_file() or digest(path) != item["sha256"]:
                atomic_bytes(path, program_path(backup, item["path"]).read_bytes())
        else:
            path.unlink(missing_ok=True)


def apply_pending(root=ROOT):
    """Called by the launcher while no studio/native DLL process owns the files."""
    root = Path(root).resolve()
    updates = root / ".updates"
    updates.mkdir(parents=True, exist_ok=True)
    with studio_lock(root), FileLock(str(updates / "update.lock"), timeout=0):
        journal_path, pending_path = updates / "journal.json", updates / "pending.json"
        if journal_path.exists():
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            if journal.get("phase") != "committed":
                _rollback(root, journal)
            journal_path.unlink()
        if not pending_path.exists():
            return False
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
        staged = _owned_directory(root, "staged", pending["stage"])
        manifest = validate_manifest(json.loads((staged / "program-manifest.json").read_text(encoding="utf-8")), pending["version"])
        if version_key(manifest["version"]) < version_key(current_version(root)):
            raise UpdateError("更新包版本低于当前版本，已拒绝回退安装")
        for item in manifest["files"]:
            source = program_path(staged, item["path"])
            if source.stat().st_size != item["size"] or digest(source) != item["sha256"]:
                raise UpdateError("待安装程序包已损坏，请重新下载更新")
        previous = root / "program-manifest.json"
        old_files = validate_manifest(json.loads(previous.read_text(encoding="utf-8")))["files"] if previous.exists() else []
        new_names = {item["path"] for item in manifest["files"]}
        removed = {item["path"] for item in old_files} - new_names
        names = sorted(new_names | removed) + ["program-manifest.json"]
        token = uuid.uuid4().hex
        backup = _owned_directory(root, "backups", token)
        entries = []
        for name in names:
            path = program_path(root, name)
            exists = path.is_file()
            item = {"path": name, "existed": exists}
            if exists:
                item["sha256"] = digest(path)
                destination = program_path(backup, name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
            entries.append(item)
        journal = {"phase": "applying", "backup": token, "files": entries}
        write_json(journal_path, journal)
        try:
            for item in manifest["files"]:
                target = program_path(root, item["path"])
                if not target.is_file() or digest(target) != item["sha256"]:
                    atomic_bytes(target, program_path(staged, item["path"]).read_bytes())
            for name in removed:
                program_path(root, name).unlink(missing_ok=True)
            atomic_bytes(previous, (staged / "program-manifest.json").read_bytes())
            journal["phase"] = "committed"
            write_json(journal_path, journal)
        except Exception as error:
            _rollback(root, journal)
            journal_path.unlink(missing_ok=True)
            raise UpdateRolledBack(f"更新未能安装，已恢复原程序，可稍后重试：{error}") from error
        pending_path.unlink()
        journal_path.unlink()
        return True


class Updates:
    def __init__(self, root=ROOT, opener=None):
        self.root = Path(root).resolve()
        self.opener = opener or urllib.request.urlopen
        self.lock = threading.RLock()
        self.worker = None
        self.state = {"status": "idle", "message": "尚未检查程序更新", "progress": 0}

    def automatic(self):
        path = self.root / ".updates/preferences.json"
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("automatic", True) is True if path.exists() else True
        except (ValueError, OSError, AttributeError):
            return False

    def set_automatic(self, value):
        if type(value) is not bool:
            raise UpdateError("自动更新选项必须是开关")
        with self.lock:
            write_json(self.root / ".updates/preferences.json", {"automatic": value})
        return self.status()

    def status(self):
        with self.lock:
            try:
                version = current_version(self.root)
            except (ValueError, OSError):
                return {"status": "failed", "current_version": VERSION, "automatic": False, "managed": False,
                        "message": "程序清单损坏，自动更新已停用；请重新解压Release程序包，不影响现有模型与用户数据"}
            result = {**self.state, "current_version": version, "automatic": self.automatic(),
                      "managed": (self.root / "program-manifest.json").exists()}
            pending = self.root / ".updates/pending.json"
            if pending.exists() and result["status"] not in {"downloading", "checking"}:
                try:
                    value = json.loads(pending.read_text(encoding="utf-8"))
                    version_key(value["version"])
                    result.update(status="ready", latest_version=value["version"], message="程序更新已下载，关闭工作台后重新启动即可安装")
                except (ValueError, OSError, KeyError, TypeError):
                    result.update(status="failed", message="待更新记录损坏，请重新下载程序更新；当前程序未被修改")
            return result

    def start(self, download=False, automatic=False):
        with self.lock:
            if automatic and (not self.automatic() or not (self.root / "program-manifest.json").exists()):
                return self.status()
            if self.worker and self.worker.is_alive():
                return self.status()
            if download and not (self.root / "program-manifest.json").exists():
                raise UpdateError("当前为源码运行，请下载Release程序包后使用自动更新")
            self.state = {"status": "checking", "message": "正在检查GitHub程序更新", "progress": 0}
            self.worker = threading.Thread(target=self._run, args=(download or automatic,), name="ming-program-update", daemon=True)
            self.worker.start()
            return self.status()

    def _set(self, **values):
        with self.lock:
            self.state.update(values)

    def _request(self, url):
        return self.opener(urllib.request.Request(url, headers={"User-Agent": "Ming3-TTS-T8-Updater", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}), timeout=25)

    def _run(self, download):
        updates = self.root / ".updates"
        archive = None
        try:
            updates.mkdir(parents=True, exist_ok=True)
            with FileLock(str(updates / "download.lock"), timeout=0):
                with self._request(f"https://api.github.com/repos/{REPOSITORY}/releases/latest") as response:
                    body = response.read(2 * 1024**2 + 1)
                if len(body) > 2 * 1024**2:
                    raise UpdateError("发布信息超过允许大小")
                release = json.loads(body)
                latest = release.get("tag_name", "").removeprefix("v")
                if release.get("draft") or release.get("prerelease"):
                    raise UpdateError("自动更新只接受正式发布版本")
                if version_key(latest) <= version_key(current_version(self.root)):
                    self._set(status="up_to_date", latest_version=latest, message="当前已是最新程序版本")
                    return
                asset = next((item for item in release.get("assets", []) if item.get("name") == ASSET_NAME), None)
                if not asset:
                    raise UpdateError("最新发布暂未提供程序更新包，可稍后重试")
                checksum = asset.get("digest", "")
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", checksum):
                    raise UpdateError("GitHub未提供有效的程序包校验值")
                expected_url = f"https://github.com/{REPOSITORY}/releases/download/v{latest}/{ASSET_NAME}"
                if asset.get("browser_download_url") != expected_url or type(asset.get("size")) is not int or not 0 < asset["size"] <= MAX_ARCHIVE:
                    raise UpdateError("程序包来源或大小无效")
                self._set(status="available", latest_version=latest, message=f"发现程序更新 {latest}")
                if not download:
                    return
                self._set(status="downloading", message="正在下载程序更新，不会下载Python或模型")
                descriptor, name = tempfile.mkstemp(prefix="program-", suffix=".zip", dir=updates)
                archive = Path(name)
                total, checksum_value = 0, hashlib.sha256()
                with os.fdopen(descriptor, "wb") as output, self._request(expected_url) as response:
                    while block := response.read(1024**2):
                        total += len(block)
                        if total > asset["size"]:
                            raise UpdateError("程序下载长度超过发布信息")
                        output.write(block)
                        checksum_value.update(block)
                        self._set(progress=total / asset["size"])
                if total != asset["size"] or checksum_value.hexdigest() != checksum[7:]:
                    raise UpdateError("程序包SHA256校验失败，原程序未被修改")
                self.stage_archive(archive, latest)
                self._set(status="ready", progress=1, message="程序更新已下载，关闭工作台后重新启动即可安装")
        except Exception as error:
            self._set(status="failed", message=f"程序更新未完成：{error}；可稍后重试，不影响当前使用")
        finally:
            if archive is not None:
                archive.unlink(missing_ok=True)

    def stage_archive(self, filename, version):
        token = uuid.uuid4().hex
        staged = _owned_directory(self.root, "staged", token)
        with zipfile.ZipFile(filename) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(set(name.casefold() for name in names)) != len(names) or len(names) > 5001:
                raise UpdateError("程序包包含重复文件或过多文件")
            if sum(item.file_size for item in infos) > MAX_CONTENT + 2 * 1024**2:
                raise UpdateError("程序包解压后过大")
            if archive.getinfo("program-manifest.json").file_size > 2 * 1024**2:
                raise UpdateError("程序清单过大")
            manifest_bytes = archive.read("program-manifest.json")
            manifest = validate_manifest(json.loads(manifest_bytes), version)
            expected = {item["path"] for item in manifest["files"]} | {"program-manifest.json"}
            if set(names) != expected:
                raise UpdateError("程序包文件与清单不一致")
            for item in manifest["files"]:
                info = archive.getinfo(item["path"])
                if info.file_size != item["size"]:
                    raise UpdateError("程序文件长度与清单不一致")
                target = program_path(staged, item["path"])
                value = archive.read(info)
                if hashlib.sha256(value).hexdigest() != item["sha256"]:
                    raise UpdateError("程序文件SHA256校验失败")
                atomic_bytes(target, value)
            atomic_bytes(staged / "program-manifest.json", manifest_bytes)
        write_json(self.root / ".updates/pending.json", {"stage": token, "version": version})


UPDATES = Updates()
