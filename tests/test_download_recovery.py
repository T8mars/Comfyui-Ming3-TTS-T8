import subprocess
import sys


def test_cancel_tolerates_process_exiting_between_poll_and_lookup(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import psutil
    from ming_t8 import downloads
    manager = downloads.Downloads()
    manager.process = SimpleNamespace(pid=12345, poll=lambda: None, terminate=Mock())
    monkeypatch.setattr(psutil, "Process", Mock(side_effect=psutil.NoSuchProcess(12345)))
    assert manager.cancel()["status"] == "cancelled"


def test_active_download_lock_and_immediate_resume_after_process_exit(tmp_path, monkeypatch):
    from ming_t8 import downloads
    monkeypatch.setattr(downloads, "configuration", lambda: {"data_root": str(tmp_path)})
    root = tmp_path / "models/Ming-Comfy-INT8"
    (root / "checkpoints").mkdir(parents=True)
    # A fresh range checkpoint must not be mistaken for a live process.
    (root / "checkpoints/ming_tts_tiny_int8_convrot.safetensors.part.ranges.json").write_text("{}")
    code = "from filelock import FileLock;import sys;lock=FileLock(sys.argv[1]);lock.acquire();print('LOCKED',flush=True);sys.stdin.readline();lock.release()"
    child = subprocess.Popen([sys.executable, "-c", code, str(root / ".download.lock")],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    manager = downloads.Downloads()
    monkeypatch.setattr(manager, "_run", lambda root: None)
    try:
        assert child.stdout.readline().strip() == "LOCKED"
        import pytest
        with pytest.raises(ValueError, match="已有模型下载正在运行"):
            manager.start()
        from scripts import download_models
        from filelock import Timeout
        monkeypatch.setattr(sys, "argv", ["download_models.py", "comfy", "--root", str(tmp_path / "models")])
        monkeypatch.setattr(download_models, "fetch_json", lambda url: [])
        with pytest.raises(Timeout):
            download_models.main()
        child.terminate()
        child.wait(timeout=10)
        assert manager.start()["status"] == "downloading"
        manager.worker.join(timeout=2)
        download_models.main()
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=10)


def test_download_start_waits_for_peer_finishing_its_file_handle(tmp_path, monkeypatch):
    from ming_t8 import downloads
    monkeypatch.setattr(downloads, "configuration", lambda: {"data_root": str(tmp_path)})
    root = tmp_path / "models/Ming-Comfy-INT8"
    root.mkdir(parents=True)
    code = "from filelock import FileLock;import sys,time;lock=FileLock(sys.argv[1]);lock.acquire();print('LOCKED',flush=True);sys.stdin.readline();time.sleep(.2);lock.release()"
    child = subprocess.Popen([sys.executable, "-c", code, str(root / ".download.lock")],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    manager = downloads.Downloads()
    monkeypatch.setattr(manager, "_run", lambda root: None)
    try:
        assert child.stdout.readline().strip() == "LOCKED"
        child.stdin.write("FINISH\n")
        child.stdin.flush()
        assert manager.start()["status"] == "downloading"
        child.wait(timeout=5)
        manager.worker.join(timeout=2)
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
