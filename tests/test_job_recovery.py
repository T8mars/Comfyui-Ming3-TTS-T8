import time


def test_restart_recovers_old_active_jobs_beyond_history_limit(tmp_path, monkeypatch):
    from ming_t8.jobs import JobQueue
    from ming_t8.storage import Store

    store = Store(tmp_path / "jobs.sqlite")
    queued = store.put("job", {"status": "queued", "payload": {}})
    running = store.put("job", {"status": "running", "payload": {}})
    cancelling = store.put("job", {"status": "cancelling", "payload": {}})
    for _ in range(1000):
        store.put("job", {"status": "complete", "payload": {}})
    recent = store.put("job", {"status": "queued", "payload": {}})
    monkeypatch.setattr(JobQueue, "_work", lambda self: None)

    queue = JobQueue(store)
    queue.worker.join(timeout=2)
    try:
        assert store.get("job", running["id"])["status"] == "interrupted"
        assert store.get("job", cancelling["id"])["status"] == "interrupted"
        assert queue.pending.qsize() == 2
        assert queue.pending.get_nowait() == queued["id"]
        assert queue.pending.get_nowait() == recent["id"]
        assert set(queue.cancel_events) == {queued["id"], recent["id"]}
    finally:
        store.close()


def test_oom_preserves_completed_segments_and_queue_recovers(tmp_path, monkeypatch):
    monkeypatch.setenv("MING_T8_DATA", str(tmp_path))
    from ming_t8.jobs import JobQueue
    from ming_t8.storage import Store

    queue = JobQueue(Store(tmp_path / "jobs.sqlite"))
    calls = []

    def execute(identifier, payload):
        calls.append(identifier)
        if len(calls) == 1:
            queue.store.update("job", identifier, completed_segments=[{"index": 0, "audio": "saved.wav"}])
            raise RuntimeError("CUDA out of memory. test injection")
        return {"audio": "next.wav"}

    monkeypatch.setattr(queue, "_execute", execute)
    try:
        job = queue.submit({"request": {"task": "ip", "text": "你好", "ip": "灵小柔"}})
        deadline = time.monotonic() + 5
        while (job := queue.store.get("job", job["id"]))["status"] not in {"failed", "complete"}:
            assert time.monotonic() < deadline
            time.sleep(.01)
        assert job["status"] == "failed" and "显存不足" in job["message"]
        assert job["completed_segments"][0]["audio"] == "saved.wav"
        retried = queue.retry(job["id"])
        while (retried := queue.store.get("job", retried["id"]))["status"] not in {"failed", "complete"}:
            assert time.monotonic() < deadline
            time.sleep(.01)
        assert retried["status"] == "complete"
        assert retried["payload"]["retry_of"] == job["id"]
    finally:
        queue.stopping = True
        queue.worker.join(timeout=2)
        queue.store.close()
