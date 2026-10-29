import io
import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient


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
