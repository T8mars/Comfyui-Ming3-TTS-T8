"""Local studio API. Every inference call executes in this process."""
from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import PROJECT_ROOT, configuration, data_directory
from .contracts import capabilities
from .jobs import JobQueue


def model_status():
    settings = configuration()
    target = Path(settings["model_path"])
    fraction = 1.0 if target.is_file() else 0.0
    checkpoint = target.with_name(target.name + ".part.ranges.json")
    if not target.is_file() and checkpoint.is_file():
        try:
            state = json.loads(checkpoint.read_text(encoding="utf-8"))
            fraction = (state["prefix"] + sum(min(state.get("chunk_size", 64 * 1024**2), state["size"] - item) for item in state["done"])) / state["size"]
        except (OSError, ValueError, KeyError):
            pass
    assets = Path(settings["assets_path"])
    weights_ready = target.is_file()
    if target.is_dir() and (target / "model.safetensors.index.json").is_file():
        index = json.loads((target / "model.safetensors.index.json").read_text(encoding="utf-8"))
        weights_ready = all((target / name).is_file() for name in set(index["weight_map"].values()))
        fraction = 1 if weights_ready else 0
    missing=[] if weights_ready else [str(target)]
    missing += [str(assets/name) for name in ("config.json","tokenizer.json","campplus.onnx") if not (assets/name).is_file()]
    return {"ready": not missing,"missing":missing,"download_bytes":9_069_165_598 if target.suffix==".safetensors" else None,
            "path": str(target), "assets_path": str(assets), "download_fraction": fraction,
            "format": "INT8 ConvRot" if target.suffix == ".safetensors" else "BF16"}


def create_app():
    jobs = JobQueue()
    store = jobs.store

    @asynccontextmanager
    async def lifespan(app):
        yield
        from .downloads import DOWNLOADS
        if DOWNLOADS.process is not None:
            DOWNLOADS.cancel()
        jobs.shutdown()

    app = FastAPI(title="T8 Ming 3.0 本地语音工作台", lifespan=lifespan)
    app.state.jobs = jobs

    @app.exception_handler(ValueError)
    async def invalid_value(request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(KeyError)
    async def missing_value(request, error):
        return JSONResponse({"detail": "未找到对应的本地记录"}, status_code=404)

    @app.exception_handler(FileNotFoundError)
    async def missing_file(request, error):
        return JSONResponse({"detail": "未找到对应文件，请重新选择或导入工程"}, status_code=404)

    @app.get("/api/status")
    def status():
        from .asr import ASR
        from .engine import MODEL_MANAGER
        from .downloads import DOWNLOADS
        return {"version": "0.1.0", "model": model_status(), "asr": ASR.available(), "download": DOWNLOADS.status(),
                "loaded": MODEL_MANAGER.engine is not None, "active_job": jobs.active,
                "data_root": configuration()["data_root"], "python": f"{sys.version_info.major}.{sys.version_info.minor}"}

    @app.get("/api/settings")
    def get_settings():
        return configuration()

    @app.post("/api/settings")
    def update_settings(payload: dict):
        if jobs.active:
            raise ValueError("请等待当前任务完成或取消后再更换模型设置")
        from .config import save_configuration
        from .engine import MODEL_MANAGER
        from .asr import ASR
        result = save_configuration(payload)
        MODEL_MANAGER.unload()
        ASR.unload()
        return result

    @app.post("/api/paths/select")
    def select_path(payload: dict):
        from .path_picker import choose_path
        return choose_path(payload.get("kind"),payload.get("initial", ""))

    @app.post("/api/models/download")
    def download_models():
        from .downloads import DOWNLOADS
        return DOWNLOADS.start()

    @app.post("/api/models/download/cancel")
    def stop_download():
        from .downloads import DOWNLOADS
        return DOWNLOADS.cancel()

    @app.get("/api/capabilities")
    def get_capabilities():
        return capabilities()

    @app.get("/api/voices")
    def voices():
        catalog = json.loads((PROJECT_ROOT / "ming_t8/assets/voices.json").read_text(encoding="utf-8"))
        return {**catalog, "saved": store.list("voice", 1000)}

    @app.post("/api/voices")
    def save_voice(payload: dict):
        if not str(payload.get("name", "")).strip():
            raise ValueError("请填写声音名称")
        if not payload.get("path") or not Path(payload["path"]).is_file():
            raise ValueError("请先准备参考录音")
        return store.put("voice", payload, payload.get("id"))

    @app.delete("/api/voices/{identifier}")
    def remove_voice(identifier: str):
        store.delete("voice", identifier)
        return {"removed": True}

    @app.post("/api/audio/upload")
    async def upload_audio(file: UploadFile = File(...)):
        path = data_directory("uploads") / (uuid.uuid4().hex + Path(file.filename or "audio.wav").suffix.lower())
        total = 0
        digest = hashlib.sha256()
        try:
            with path.open("wb") as destination:
                while block := await file.read(1024 * 1024):
                    total += len(block)
                    if total > 512 * 1024**2:
                        raise ValueError("单段音频文件超过512MiB")
                    destination.write(block)
                    digest.update(block)
            from .audio import inspect_audio
            return {"path": str(path), "sha256": digest.hexdigest(), "name": file.filename,
                    **inspect_audio(path)}
        except Exception:
            path.unlink(missing_ok=True)
            raise

    @app.post("/api/audio/prepare")
    def prepare_audio(payload: dict):
        from .audio import prepare_reference
        return prepare_reference(payload["path"], payload.get("start", 0), payload.get("end"))

    @app.post("/api/audio/inspect")
    def inspect_reference(payload: dict):
        from .audio import inspect_audio
        return {"path": payload["path"], **inspect_audio(payload["path"])}

    @app.get("/api/audio/file")
    def listen_reference(path: str):
        filename = Path(path).resolve(strict=True)
        root = Path(configuration()["data_root"]).resolve()
        if not filename.is_relative_to(root) or filename.suffix.lower() not in (".wav", ".flac", ".mp3", ".ogg", ".m4a", ".webm"):
            raise ValueError("只能试听工作台中已准备的音频")
        return FileResponse(filename)

    @app.post("/api/batch/preview")
    def preview_batch(payload: dict):
        from .batch import preview_batch
        return preview_batch(**payload)

    @app.post("/api/jobs")
    def submit(payload: dict):
        return jobs.submit(payload)

    @app.get("/api/jobs")
    def list_jobs():
        return store.list("job", 200)

    @app.get("/api/jobs/{identifier}")
    def get_job(identifier: str):
        return store.get("job", identifier)

    @app.post("/api/jobs/{identifier}/cancel")
    def cancel_job(identifier: str):
        return jobs.cancel(identifier)

    @app.post("/api/jobs/{identifier}/retry")
    def retry_job(identifier: str):
        return jobs.retry(identifier)

    def artifact_path(identifier, filename):
        folder = (data_directory("jobs") / identifier).resolve()
        if not identifier.isalnum() or Path(filename).name != filename:
            raise ValueError("无效的任务文件路径")
        path = (folder / filename).resolve()
        if path.parent != folder or not path.is_file():
            raise HTTPException(404, "此文件尚未生成")
        return path

    @app.get("/api/artifacts/{identifier}/{filename}")
    def artifact(identifier: str, filename: str):
        return FileResponse(artifact_path(identifier, filename))

    @app.get("/api/export/{identifier}/{kind}")
    def export(identifier: str, kind: str):
        job = store.get("job", identifier)
        result = job.get("result") or {}
        if kind in ("wav", "flac", "mp3"):
            from .audio import export_audio
            source = artifact_path(identifier, result.get("audio_file", "output.wav"))
            path = export_audio(source, kind)
        elif kind in ("json", "txt") and job["payload"].get("operation") == "transcribe":
            path = artifact_path(identifier, "transcript." + kind)
        elif kind == "json":
            path = artifact_path(identifier,"result.json")
        elif kind in ("srt", "vtt"):
            from .exports import subtitles
            path = data_directory("jobs") / identifier / ("subtitle." + kind)
            path.write_text(subtitles(result, kind), encoding="utf-8")
        else:
            raise ValueError("不支持此导出格式")
        return FileResponse(path, filename=path.name)

    @app.post("/api/projects")
    def save_project(payload: dict):
        from .projects import validate_project
        validate_project(payload)
        return store.put("project", payload, payload.get("id"))

    @app.get("/api/projects")
    def list_projects():
        return store.list("project", 200)

    @app.get("/api/projects/{identifier}/export")
    def download_project(identifier: str):
        from .projects import export_project
        return FileResponse(export_project(store.get("project", identifier)), filename="Ming语音工程.mingstudio.zip")

    @app.post("/api/projects/import")
    async def upload_project(file: UploadFile = File(...)):
        from .projects import import_project
        payload = await file.read(512 * 1024**2 + 1)
        if len(payload) > 512 * 1024**2:
            raise ValueError("工程文件超过512MiB")
        path = data_directory("uploads") / (uuid.uuid4().hex + ".zip")
        path.write_bytes(payload)
        return store.put("project", import_project(path))

    @app.post("/api/models/unload")
    def unload():
        if jobs.active:
            raise ValueError("请先等待当前任务完成，或取消任务")
        from .engine import MODEL_MANAGER
        from .asr import ASR
        MODEL_MANAGER.unload()
        ASR.unload()
        return {"released": True}

    @app.post("/api/folders/{kind}")
    def open_folder(kind: str):
        import os
        if kind not in ("jobs", "projects", "references", "validation"):
            raise ValueError("不支持此目录")
        path = data_directory(kind)
        if hasattr(os, "startfile"):
            os.startfile(str(path))
        return {"path": str(path)}

    @app.get("/")
    def index():
        return FileResponse(PROJECT_ROOT / "studio/index.html")

    app.mount("/studio", StaticFiles(directory=str(PROJECT_ROOT / "studio")), name="studio")
    return app
