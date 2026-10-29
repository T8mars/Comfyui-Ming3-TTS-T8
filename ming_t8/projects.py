"""Portable project archives containing JSON and explicit audio resources."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import uuid
import zipfile

from .config import data_directory


def _requests(project):
    if project.get("request"):
        yield project["request"]
    for segment in project.get("segments", []):
        if segment.get("request"):
            yield segment["request"]


def _resource_holders(project):
    yield from _requests(project)
    for character in project.get("characters",[]):
        if character.get("prompt_wav"):
            yield character


def validate_project(project):
    from .contracts import TaskRequest
    if not isinstance(project, dict):
        raise ValueError("工程内容必须是对象")
    segments = project.get("segments", [])
    if not isinstance(segments, list) or any(not isinstance(item, dict) for item in segments):
        raise ValueError("工程片段必须是对象列表")
    characters = project.get("characters", [])
    if not isinstance(characters, list):
        raise ValueError("工程角色必须是列表")
    requests = list(_requests(project))
    if not requests:
        raise ValueError("工程至少需要一段有效的生成设置")
    if len(requests) > 1000:
        raise ValueError("工程最多包含1000个片段")
    for request in requests:
        TaskRequest.from_dict(request)
    for character in project.get("characters",[]):
        if not isinstance(character,dict):
            raise ValueError("工程角色格式不正确")
        if character.get("prompt_wav"):
            TaskRequest.from_dict({"task":"seed","text":"工程角色","prompt_wav":character["prompt_wav"],
                                  "prompt_text":character.get("prompt_text"),"target_language":"Chinese"})


def export_project(project, destination=None):
    validate_project(project)
    value = deepcopy(project)
    value["schema_version"] = 1
    for segment in value.get("segments",[]):
        segment.pop("reuse_from",None)
    resources = {}
    for request in _resource_holders(value):
        paths = request.get("prompt_wav")
        if paths is None:
            continue
        is_list = isinstance(paths, list)
        replaced = []
        for item in paths if is_list else [paths]:
            path = Path(item).resolve(strict=True)
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            suffix = path.suffix.lower()
            if suffix not in (".wav", ".flac", ".mp3", ".ogg", ".m4a"):
                raise ValueError("工程仅打包已支持的参考音频格式")
            name = f"resources/{digest}{suffix}"
            resources[name] = {"data": data, "sha256": digest}
            replaced.append(name)
        request["prompt_wav"] = replaced if is_list else replaced[0]
    value["resources"] = {name: {"sha256": item["sha256"], "size": len(item["data"])} for name, item in resources.items()}
    destination = Path(destination or data_directory("projects") / f"project-{uuid.uuid4().hex[:12]}.mingstudio.zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.json", json.dumps(value, ensure_ascii=False, indent=2))
        for name, item in resources.items():
            archive.writestr(name, item["data"])
    return destination


def import_project(filename):
    try:
        return _import_project(filename)
    except (zipfile.BadZipFile, KeyError, UnicodeError) as error:
        raise ValueError("工程文件损坏或缺少必要内容，请重新导出工程") from error


def _import_project(filename):
    target = data_directory("projects") / uuid.uuid4().hex
    with zipfile.ZipFile(filename) as archive:
        if sum(info.file_size for info in archive.infolist()) > 512 * 1024 * 1024:
            raise ValueError("工程解压后超过512MiB")
        for info in archive.infolist():
            path = PurePosixPath(info.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or ":" in info.filename:
                raise ValueError("工程包含无效的资源路径")
        if len({info.filename for info in archive.infolist()}) != len(archive.infolist()):
            raise ValueError("工程包含重复文件名")
        value = json.loads(archive.read("project.json"))
        if not isinstance(value, dict):
            raise ValueError("工程内容必须是对象")
        if value.get("schema_version") != 1:
            raise ValueError("不支持此工程版本")
        descriptions = value.get("resources", {})
        if not isinstance(descriptions, dict):
            raise ValueError("工程资源清单必须是对象")
        validate_project(value)
        resources = {}
        for name, description in descriptions.items():
            if not name.startswith("resources/"):
                raise ValueError("工程资源必须位于resources目录")
            if (not isinstance(description, dict) or type(description.get("size")) is not int
                    or description["size"] < 0 or not isinstance(description.get("sha256"), str)):
                raise ValueError("工程资源校验信息不正确")
            data = archive.read(name)
            if len(data) != description["size"] or hashlib.sha256(data).hexdigest() != description["sha256"]:
                raise ValueError("工程音频资源校验失败")
            suffix = PurePosixPath(name).suffix.lower()
            if suffix not in (".wav", ".flac", ".mp3", ".ogg", ".m4a"):
                raise ValueError("工程包含不支持的音频资源")
            resources[name] = (target / (hashlib.sha256(data).hexdigest() + suffix), data)
        for request in _resource_holders(value):
            paths = request.get("prompt_wav")
            if paths is None:
                continue
            is_list = isinstance(paths, list)
            items = paths if is_list else [paths]
            if any(item not in resources for item in items):
                raise ValueError("工程缺少必要的参考音频")
            request["prompt_wav"] = [str(resources[item][0]) for item in items] if is_list else str(resources[items[0]][0])
        # Validate semantic requests before saving any resources.
        validate_project(value)
        target.mkdir(parents=True, exist_ok=True)
        for path, data in resources.values():
            path.write_bytes(data)
        (target / "project.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return value
