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


def test_concurrent_component_installations_use_independent_partial_files(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    barrier = threading.Barrier(2)
    first_finished = threading.Event()

    class SynchronizedResponse(io.BytesIO):
        def __init__(self, payload, second):
            super().__init__(payload)
            self.second = second

        def __exit__(self, *args):
            super().__exit__(*args)
            barrier.wait(timeout=5)  # Both output handles are closed before replacing.
            if self.second:
                assert first_finished.wait(timeout=5)

    target = tmp_path / "component.dll"
    payload = b"verified component"
    checksum = hashlib.sha256(payload).hexdigest()
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(install.download_component, target, "unused", len(payload), checksum,
                            lambda *args, **kwargs: SynchronizedResponse(payload, False))
        first.add_done_callback(lambda future: first_finished.set())
        second = pool.submit(install.download_component, target, "unused", len(payload), checksum,
                             lambda *args, **kwargs: SynchronizedResponse(payload, True))
        futures = [first, second]
        assert all(future.result(timeout=10) for future in futures)
    assert target.read_bytes() == payload
    assert list(tmp_path.glob("*.part")) == []
