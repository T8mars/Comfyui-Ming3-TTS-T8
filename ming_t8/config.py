from __future__ import annotations

import json
import os
from pathlib import Path
from filelock import FileLock

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def configuration():
    settings_path = PROJECT_ROOT / "settings.local.json"
    with FileLock(str(settings_path) + ".lock"):
        settings = json.loads(settings_path.read_text(encoding="utf-8-sig")) if settings_path.is_file() else {}
    bundled = PROJECT_ROOT / "data"
    development = Path("D:/Ming3-TTS-data")
    fallback = bundled if bundled.exists() or not development.exists() else development
    root = Path(os.environ.get("MING_T8_DATA", settings.get("data_root", str(fallback)))).expanduser().resolve()
    defaults = {
        "data_root": str(root),
        "model_path": str(root / "models/Ming-Comfy-INT8/checkpoints/ming_tts_tiny_int8_convrot.safetensors"),
        "assets_path": str(root / "models/Ming-3.0-tts-tiny"),
        "asr_root": str(PROJECT_ROOT / "components/confucius"),
        "device": "cuda:0", "attention_backend": "sdpa", "host": "127.0.0.1", "port": 7863,
        "native_kernels": "auto", "cuda_graphs": True,
    }
    defaults.update(settings)
    defaults["data_root"] = str(root)
    return defaults


def save_configuration(values):
    allowed = {"model_path", "assets_path", "asr_root", "device", "native_kernels", "attention_backend", "cuda_graphs"}
    if not isinstance(values, dict) or set(values)-allowed:
        raise ValueError("不支持的设置字段")
    for key in ("model_path", "assets_path", "asr_root"):
        if key in values:
            path = Path(str(values[key])).expanduser().resolve()
            if not path.exists():
                raise ValueError(f"此路径不存在：{path}")
            values[key] = str(path)
    if values.get("native_kernels", "portable") not in ("portable", "auto", "native"):
        raise ValueError("请选择原生加速或兼容计算")
    if values.get("attention_backend", "sdpa") not in ("sdpa", "auto", "flash_attention_2"):
        raise ValueError("不支持的注意力后端")
    if values.get("device", "cuda:0") not in ("cuda:0", "cpu"):
        raise ValueError("不支持的设备")
    if "cuda_graphs" in values and type(values["cuda_graphs"]) is not bool:
        raise ValueError("CUDA Graph设置必须为开关")
    path = PROJECT_ROOT / "settings.local.json"
    with FileLock(str(path) + ".lock"):
        settings = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
        settings.update(values)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    return configuration()


def data_directory(name):
    root = Path(configuration()["data_root"])
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    return path
