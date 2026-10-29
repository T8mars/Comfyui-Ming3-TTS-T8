"""Managed asset downloads. This process never hosts inference for another process."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import threading
from filelock import FileLock, Timeout

from .config import PROJECT_ROOT, configuration, data_directory


class Downloads:
    def __init__(self):
        self.lock = threading.RLock()
        self.process = None
        self.worker = None
        self.state = {"status": "idle", "message": "尚未启动模型下载"}

    def status(self):
        with self.lock:
            return dict(self.state)

    def start(self):
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                return self.status()
            root = Path(configuration()["data_root"]) / "models"
            for name in ("Ming-3.0-tts-tiny", "Ming-Comfy-INT8"):
                folder = root / name
                folder.mkdir(parents=True, exist_ok=True)
                try:
                    # Windows can briefly retain a closing process's file handle.
                    with FileLock(str(folder / ".download.lock"), timeout=0.5, poll_interval=0.025):
                        pass
                except Timeout as error:
                    raise ValueError("已有模型下载正在运行，请等待当前下载完成；进度会自动更新") from error
            self.state = {"status": "downloading", "message": "正在下载固定版本的主模型与必要辅助文件"}
            self.worker = threading.Thread(target=self._run, args=(root,), name="ming-model-download", daemon=True)
            self.worker.start()
            return self.status()

    def _run(self, root):
        log = data_directory("logs") / "model-download.log"
        try:
            with log.open("a", encoding="utf-8") as output:
                for arguments in (["official", "--assets-only"], ["comfy"]):
                    with self.lock:
                        if self.state["status"] == "cancelled":
                            return
                        self.process = subprocess.Popen([sys.executable,"-X","utf8","-u",str(PROJECT_ROOT / "scripts/download_models.py"),
                            *arguments,"--root",str(root),"--workers","16"],cwd=PROJECT_ROOT,
                            stdout=output,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
                    code = self.process.wait()
                    if code:
                        raise RuntimeError(f"下载未完成（{code}），可再次点击继续；详情见{log}")
                with self.lock:
                    self.state = {"status":"complete","message":"模型下载与SHA256校验完成"}
        except Exception as error:
            with self.lock:
                if self.state["status"] != "cancelled":
                    self.state = {"status":"failed","message":str(error)}
        finally:
            with self.lock:
                self.process = None

    def cancel(self):
        with self.lock:
            self.state = {"status":"cancelled","message":"下载已停止，已校验的断点仍保留"}
            if self.process is not None and self.process.poll() is None:
                import psutil
                parent = psutil.Process(self.process.pid)
                for child in reversed(parent.children(recursive=True)):
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                self.process.terminate()
            return self.status()


DOWNLOADS = Downloads()
