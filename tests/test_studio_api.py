import io
import numpy as np
import soundfile as sf
import pytest
from fastapi.testclient import TestClient


def test_saving_settings_cannot_unload_a_job_that_starts_during_save(tmp_path, monkeypatch):
    import threading
    from ming_t8 import config
    from ming_t8.asr import ASR
    from ming_t8.engine import MODEL_MANAGER
    monkeypatch.setenv("MING_T8_DATA", str(tmp_path))
    from ming_t8.server import create_app
    app = create_app()
    jobs = app.state.jobs
    started, finish = threading.Event(), threading.Event()
    violations = []

    def execute(*args):
        started.set()
        assert finish.wait(timeout=5)
        return {"text": "done"}

    def save(values):
        jobs.submit({"request": {"task": "ip", "text": "你好", "ip": "灵小柔"}})
        started.wait(timeout=.2)
        return values

    def unload():
        if jobs.active:
            violations.append(jobs.active)
        finish.set()

    monkeypatch.setattr(jobs, "_execute", execute)
    monkeypatch.setattr(config, "save_configuration", save)
    monkeypatch.setattr(MODEL_MANAGER, "unload", unload)
    monkeypatch.setattr(ASR, "unload", lambda: None)
    with TestClient(app) as client:
        response = client.post("/api/settings", json={"device": "cpu"})
        finish.set()
        assert response.status_code == 200
        assert violations == [], "a model must not be unloaded after a job has claimed it"


def test_job_poll_keeps_running_and_watched_jobs_beyond_recent_history(tmp_path, monkeypatch):
    monkeypatch.setenv("MING_T8_DATA", str(tmp_path))
    from ming_t8.jobs import JobQueue
    monkeypatch.setattr(JobQueue, "_work", lambda self: None)
    from ming_t8.server import create_app
    app = create_app()
    store = app.state.jobs.store
    watched = store.put("job", {"status": "complete", "created_at": 1})
    running = store.put("job", {"status": "running", "created_at": 2})
    for index in range(201):
        store.put("job", {"status": "complete", "created_at": index + 3})
    # The former endpoint returned only this list and lost both older jobs.
    assert watched["id"] not in {item["id"] for item in store.list("job", 200)}
    assert running["id"] not in {item["id"] for item in store.list("job", 200)}
    with TestClient(app) as client:
        assert running["id"] in {item["id"] for item in client.get("/api/jobs").json()}
        polled = client.get("/api/jobs", params={"watch": watched["id"]}).json()
        assert {watched["id"], running["id"]}.issubset({item["id"] for item in polled})
        assert client.get("/api/jobs", params={"watch": "../invalid"}).status_code == 400
        for payload in ({}, {"operation": "batch", "segments": [None]}, {"operation": "transcribe", "audio_path": None}):
            assert client.post("/api/jobs", json=payload).status_code == 400


def test_studio_api_reference_batch_and_project(tmp_path, monkeypatch):
    monkeypatch.setenv("MING_T8_DATA", str(tmp_path))
    from ming_t8.server import create_app
    with TestClient(create_app()) as client:
        assert client.get("/").status_code == 200
        assert len(client.get("/api/capabilities").json()) == 10
        assert len(client.get("/api/voices").json()["voices"]) == 546
        buffer = io.BytesIO()
        sf.write(buffer, np.sin(np.arange(32000) / 50) * .05, 16000, format="WAV")
        result = client.post("/api/audio/upload", files={"file": ("中文 参考.wav", buffer.getvalue(), "audio/wav")})
        assert result.status_code == 200
        audio = result.json()
        cropped = client.post("/api/audio/prepare", json={"path": audio["path"], "start": .2, "end": 1.2}).json()
        assert cropped["seconds"] == 1
        base = {"task": "seed", "text": "你好", "prompt_wav": cropped["path"], "prompt_text": "参考文字", "target_language": "Chinese"}
        batch = client.post("/api/batch/preview", json={"template": base, "text": "第一句\n第二句", "format": "txt"})
        assert batch.status_code == 200 and batch.json()["count"] == 2
        project = client.post("/api/projects", json={"name": "测试", "segments": batch.json()["segments"]}).json()
        packed = client.get(f"/api/projects/{project['id']}/export")
        assert packed.status_code == 200
        restored = client.post("/api/projects/import", files={"file": ("工程.zip", packed.content)})
        assert restored.status_code == 200
        assert len(restored.json()["segments"]) == 2
        malformed = client.post("/api/projects/import", files={"file": ("bad.zip", b"not a zip")})
        assert malformed.status_code == 400
        assert "工程" in malformed.json()["detail"]
