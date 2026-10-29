from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ming_t8.jobs import JobQueue
from ming_t8.storage import Store


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setattr(JobQueue, "_work", lambda self: None)
    value = JobQueue(Store(tmp_path / "jobs.sqlite"))
    value.worker.join(timeout=2)
    yield value
    value.store.close()


@pytest.mark.parametrize("payload", [{}, {"operation": "batch", "segments": [None]},
    {"operation": "batch", "segments": [{}]}, {"operation": "transcribe", "audio_path": None},
    {"operation": "batch", "segments": [{"request": {"task": "ip", "text": "你好", "ip": "灵小柔"}, "pause_ms": True}]}])
def test_invalid_queue_payloads_are_validation_errors(queue, payload):
    with pytest.raises(ValueError):
        queue.submit(payload)


def test_cancel_cannot_resurrect_a_terminal_job_as_cancelling(queue, monkeypatch):
    from ming_t8.asr import ASR
    from ming_t8.engine import MODEL_MANAGER
    job = queue.store.put("job", {"status": "running", "payload": {}})
    queue.active = job["id"]

    def finish_during_cancel():
        queue.store.update("job", job["id"], status="cancelled", result={"text": "finished"})
        queue.active = None

    monkeypatch.setattr(MODEL_MANAGER, "engine", SimpleNamespace(cancel=finish_during_cancel))
    monkeypatch.setattr(ASR, "cancel", Mock())
    result = queue.cancel(job["id"])
    assert result["status"] == "cancelled"
    assert result["result"] == {"text": "finished"}


def test_fast_completion_and_cancellation_leave_no_orphaned_jobs(tmp_path, monkeypatch):
    import time
    from ming_t8.asr import ASR
    from ming_t8.engine import MODEL_MANAGER
    monkeypatch.setenv("MING_T8_DATA", str(tmp_path))
    monkeypatch.setattr(JobQueue, "_execute", lambda *args: {"text": "done"})
    monkeypatch.setattr(MODEL_MANAGER, "engine", None)
    monkeypatch.setattr(ASR, "cancel", Mock())
    jobs = JobQueue(Store(tmp_path / "live.sqlite"))
    identifiers = []
    try:
        for _ in range(100):
            job = jobs.submit({"request": {"task": "ip", "text": "你好", "ip": "灵小柔"}})
            identifiers.append(job["id"])
            jobs.cancel(job["id"])
        deadline = time.monotonic() + 5
        while jobs.pending.unfinished_tasks:
            assert time.monotonic() < deadline
            time.sleep(.01)
        assert all(jobs.store.get("job", identifier)["status"] in {"complete", "cancelled"} for identifier in identifiers)
    finally:
        jobs.shutdown()
