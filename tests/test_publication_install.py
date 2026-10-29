import hashlib
import io
import json
from pathlib import Path

import pytest
import install
from scripts.fetch_models import configure_paths


@pytest.mark.parametrize("relative",["../outside.dll","components/../../outside.dll","C:/outside.dll","components\\outside.dll"])
def test_component_paths_cannot_escape_installation(tmp_path,relative):
    with pytest.raises(ValueError):install.safe_target(tmp_path,relative)


def test_corrupted_component_does_not_replace_existing_file(tmp_path):
    target=tmp_path/"ming_cuda.dll";target.write_bytes(b"existing")
    with pytest.raises(ValueError,match="integrity"):
        install.download_component(target,"unused",4,hashlib.sha256(b"good").hexdigest(),opener=lambda *args,**kwargs:io.BytesIO(b"bad!"))
    assert target.read_bytes()==b"existing" and not target.with_name(target.name+".part").exists()
    assert install.download_component(target,"unused",4,hashlib.sha256(b"good").hexdigest(),opener=lambda *args,**kwargs:io.BytesIO(b"good"))
    assert not install.download_component(target,"unused",4,hashlib.sha256(b"good").hexdigest(),opener=lambda *args,**kwargs:pytest.fail("Verified component downloaded twice"))


def test_model_setup_preserves_other_settings(tmp_path):
    project=tmp_path/"project";project.mkdir();models=tmp_path/"模型目录"
    for relative in ["Ming-Comfy-INT8/checkpoints/ming_tts_tiny_int8_convrot.safetensors","Ming-3.0-tts-tiny/campplus.onnx","Confucius4-R2T2/models/Confucius4-R2T2-GGUF/Confucius4-R2T2-Q8_0.gguf"]:
        path=models/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b"model")
    (project/"settings.local.json").write_text(json.dumps({"device":"cpu","attention_backend":"sdpa"}))
    result=configure_paths(project,models)
    assert result["device"]=="cpu" and result["attention_backend"]=="sdpa"
    assert Path(result["assets_path"])==models/"Ming-3.0-tts-tiny"
