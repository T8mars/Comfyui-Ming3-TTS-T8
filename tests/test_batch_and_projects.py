import io
import json
import zipfile

import numpy as np
import pytest
import soundfile as sf

from ming_t8.batch import preview_batch
from ming_t8.projects import export_project, import_project


def test_batch_import_roundtrip_and_numeric_controls():
    base = {"task": "ip", "text": "模板", "ip": "灵小柔"}
    imported = preview_batch(base, 'text,seed,pause_ms\n"你好，世界。",42,500\n第二句,43,0', "csv")
    assert imported["segments"][0]["request"]["seed"] == 42
    assert imported["segments"][0]["request"]["text"] == "你好，世界。"
    assert imported["segments"][1]["pause_ms"] == 0
    assert preview_batch(base, json.dumps(imported), "json") == imported
    with pytest.raises(ValueError, match="第1个片段"):
        preview_batch(base, "text,temperature\n错误,nan", "csv")
    mixed=preview_batch(base,json.dumps([{"request":{"task":"voice_design","text":"你好","style":"清晰女声"}}]),"json")
    assert mixed["segments"][0]["request"]["ip"] is None


def test_portable_project_moves_reference_and_detects_tampering(tmp_path, monkeypatch):
    monkeypatch.setenv("MING_T8_DATA", str(tmp_path / "迁移 目录"))
    reference = tmp_path / "中文 参考.wav"
    sf.write(str(reference), np.linspace(-.1, .1, 16000), 16000)
    project = {"name": "我的声音", "request": {"task": "seed", "text": "你好。", "prompt_wav": str(reference),
                "prompt_text": "参考录音", "target_language": "Chinese"}}
    project["characters"]=[{"id":"role-a","name":"角色甲","prompt_wav":str(reference),"prompt_text":"参考录音"}]
    archive = export_project(project)
    reference.unlink()
    restored = import_project(archive)
    assert restored["request"]["prompt_text"] == "参考录音"
    assert restored["request"]["prompt_wav"] != project["request"]["prompt_wav"]
    from pathlib import Path
    assert Path(restored["request"]["prompt_wav"]).is_file()
    assert restored["characters"][0]["prompt_wav"]==restored["request"]["prompt_wav"]
    malicious = tmp_path / "damaged.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(malicious, "w") as output:
        for name in source.namelist():
            output.writestr(name, source.read(name) if name == "project.json" else b"tampered")
    with pytest.raises(ValueError, match="校验失败"):
        import_project(malicious)
    with zipfile.ZipFile(malicious, "w") as output:
        output.writestr("../evil.wav", b"bad")
    with pytest.raises(ValueError, match="无效的资源路径"):
        import_project(malicious)
