import json
from types import SimpleNamespace
import pytest


def test_model_selection_validates_returned_path_and_cancellation(tmp_path,monkeypatch):
    from ming_t8 import path_picker
    model=tmp_path/"中文 路径"/"ming.safetensors";model.parent.mkdir();model.write_bytes(b"model")
    calls=[]
    def select(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0,stdout=json.dumps({"path":str(model)}))
    monkeypatch.setattr(path_picker.subprocess,"run",select)
    result=path_picker.choose_path("model_file",str(tmp_path))
    assert result["path"]==str(model.resolve()) and not result["cancelled"]
    assert calls[0][-2:]==["--initial",str(tmp_path)]
    with pytest.raises(ValueError):path_picker.choose_path("bf16_dir")
    monkeypatch.setattr(path_picker.subprocess,"run",lambda *args,**kwargs:SimpleNamespace(returncode=0,stdout='{"path":null}'))
    assert path_picker.choose_path("assets_dir")=={"path":None,"cancelled":True}


def test_picker_api_keeps_existing_settings_until_explicit_save(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from ming_t8 import path_picker
    from ming_t8.server import create_app
    monkeypatch.setenv("MING_T8_DATA",str(tmp_path))
    monkeypatch.setattr(path_picker,"choose_path",lambda kind,initial:{"path":str(tmp_path),"cancelled":False})
    with TestClient(create_app()) as client:
        original=client.get("/api/settings").json()
        response=client.post("/api/paths/select",json={"kind":"assets_dir","initial":""})
        assert response.status_code==200 and response.json()["path"]==str(tmp_path)
        assert client.get("/api/settings").json()==original
