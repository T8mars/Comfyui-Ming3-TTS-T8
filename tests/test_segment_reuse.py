from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
import torch

from ming_t8.jobs import JobQueue
from ming_t8.storage import Store


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("MING_T8_DATA", str(tmp_path))
    monkeypatch.setattr(JobQueue, "_work", lambda self: None)
    from ming_t8.asr import ASR
    from ming_t8.engine import MODEL_MANAGER

    class Engine:
        sample_rate = 8000
        model_path = tmp_path / "model.fixture"
        identity = {"sha256": "test model"}
        execution_profile = {"backend": "cpu test"}
        load_info = {}
        calls = 0

        def generate(self, request, output_path, **kwargs):
            self.calls += 1
            pcm = np.full(160, self.calls * .1, dtype=np.float32)
            sf.write(output_path, pcm, self.sample_rate, subtype="FLOAT")
            return SimpleNamespace(waveform=torch.from_numpy(pcm).reshape(1, 1, -1)), {"truncated": False, "seconds": .001}

    engine = Engine()
    monkeypatch.setattr(MODEL_MANAGER, "get", lambda *args, **kwargs: engine)
    monkeypatch.setattr(ASR, "unload", lambda: None)
    queue = JobQueue(Store(tmp_path / "state.sqlite"))
    queue.worker.join(timeout=2)

    def run(previous=None):
        segment = {"request": {"task": "ip", "text": "完整的台词。", "ip": "灵小柔", "seed": 17}}
        if previous:
            segment["reuse_from"] = {"job_id": previous, "segment_index": 0}
        payload = {"operation": "batch", "segments": [segment]}
        job = queue.submit(payload)
        result = queue._execute(job["id"], payload)
        queue.store.update("job", job["id"], status="complete", result=result)
        return job["id"], result

    yield run, engine, tmp_path
    queue.store.close()


@pytest.mark.parametrize("damage", ["missing_job", "invalid_wav", "short_wav", "changed_wav"])
def test_stale_or_damaged_take_falls_back_to_generation(runner, damage):
    run, engine, root = runner
    previous, _ = run()
    audio = root / "jobs" / previous / "segment-0001.wav"
    if damage == "missing_job":
        previous = "f" * 32
    elif damage == "invalid_wav":
        audio.write_bytes(b"not a WAV")
    elif damage == "short_wav":
        sf.write(audio, np.zeros(8, dtype=np.float32), engine.sample_rate, subtype="FLOAT")
    else:
        sf.write(audio, np.full(160, .9, dtype=np.float32), engine.sample_rate, subtype="FLOAT")
    _, result = run(previous)
    assert result["segments"][0]["reused"] is False
    assert engine.calls == 2
    assert result["audio_seconds"] == .02


def test_valid_completed_take_is_still_reused(runner):
    run, engine, _ = runner
    previous, _ = run()
    _, result = run(previous)
    assert result["segments"][0]["reused"] is True
    assert engine.calls == 1
