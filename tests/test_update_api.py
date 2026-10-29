import io
import json

from fastapi.testclient import TestClient

from ming_t8 import updates


def test_update_api_keeps_preferences_separate_from_model_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("MING_T8_DATA", str(tmp_path / "data"))
    updates.write_json(tmp_path / "program-manifest.json", {"schema": 1, "kind": "ming-t8-program", "version": "0.2.0",
        "files": [{"path": "studio.py", "size": 0, "sha256": "0" * 64}]})

    def opener(*args, **kwargs):
        return io.BytesIO(json.dumps({"tag_name": "v0.2.0", "assets": [], "draft": False, "prerelease": False}).encode())

    manager = updates.Updates(tmp_path, opener)
    manager.set_automatic(False)
    monkeypatch.setattr(updates, "UPDATES", manager)
    from ming_t8.server import create_app
    with TestClient(create_app()) as client:
        assert client.get("/api/updates").json()["automatic"] is False
        assert client.get("/api/status").json()["version"] == updates.VERSION
        assert client.post("/api/updates/preferences", json={"automatic": "false"}).status_code == 400
        client.post("/api/updates/check")
        manager.worker.join(timeout=5)
        assert client.get("/api/updates").json()["status"] == "up_to_date"
        assert not (tmp_path / "settings.local.json").exists()
