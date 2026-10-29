"""Content identities for reproducible results and safe segment reuse."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading

_CACHE = {}
_LOCK = threading.RLock()
CORE_REVISION = "t8-native-2026-10-24.1"
PINNED_INT8_SHA256 = "37d83a48dcb20d989c48313e93f0f0876a3c81d570966c2442409cf302a03e53"


def file_digest(filename):
    path = Path(filename).resolve(strict=True)
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    with _LOCK:
        if key not in _CACHE:
            digest = hashlib.sha256()
            with path.open("rb") as source:
                for block in iter(lambda: source.read(8 * 1024**2), b""):
                    digest.update(block)
            _CACHE[key] = digest.hexdigest()
        return _CACHE[key]


def model_identity(model_path, assets_path):
    path, assets = Path(model_path), Path(assets_path)
    if path.is_file():
        files = {path.name: file_digest(path)}
        if path.name == "ming_tts_tiny_int8_convrot.safetensors" and files[path.name] != PINNED_INT8_SHA256:
            raise ValueError("主模型SHA256与已冻结的发布版本不符，请检查文件或重新下载")
    else:
        index = json.loads((path / "model.safetensors.index.json").read_text(encoding="utf-8"))
        files = {name: file_digest(path / name) for name in sorted(set(index["weight_map"].values()))}
    for name in ("config.json", "tokenizer.json", "campplus.onnx"):
        files["assets/" + name] = file_digest(assets / name)
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    package = Path(__file__).resolve().parent
    implementation = {str(source.relative_to(package)):file_digest(source) for source in package.rglob("*.py")}
    components = package.parent / "components/cuda/manifest.json"
    if components.is_file():
        implementation["cuda_component"] = file_digest(components)
    code_hash = hashlib.sha256(json.dumps(implementation,sort_keys=True).encode()).hexdigest()
    return {"sha256": digest, "files": files, "core_revision": CORE_REVISION,"implementation_sha256":code_hash}


def generation_identity(request, model):
    value = request.to_dict()
    paths = value.get("prompt_wav")
    references = [] if paths is None else [file_digest(path) for path in (paths if isinstance(paths, list) else [paths])]
    document = {"request": value, "references": references, "model": model, "core_revision": CORE_REVISION}
    return hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
