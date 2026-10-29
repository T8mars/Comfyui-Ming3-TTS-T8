"""Direct Confucius Q8 inference; no worker process and no HTTP client."""
from __future__ import annotations

import gc
import importlib.machinery
import json
from pathlib import Path
import sys
import threading
import time

import numpy as np

from .config import configuration, PROJECT_ROOT
from ._vendor.confucius.hotwords import hotword_context


class ConfuciusASR:
    def __init__(self):
        self.lock = threading.RLock()
        self.engine = None

    def available(self):
        root = Path(configuration()["asr_root"])
        abi = f"cp{sys.version_info.major}{sys.version_info.minor}"
        builds = [PROJECT_ROOT / "components/confucius/.runtime/build-native-cu128", root / ".runtime/build-native-cu128"]
        selected = next((path for path in builds if any(abi in item.name for item in (path / "python").rglob("*confucius_native*.pyd"))
                         or any(abi in item.name for item in (path / "python").rglob("qwen3asr_native*.pyd"))), builds[-1])
        compatible = [path for path in (selected / "python").rglob("*.pyd") if abi in path.name and path.name.startswith(("ming_confucius_native", "qwen3asr_native"))]
        pair=root/"models/Confucius4-R2T2-GGUF"
        models=all((pair/name).is_file() for name in ("Confucius4-R2T2-Q8_0.gguf","mmproj-Confucius4-R2T2-Q8_0.gguf"))
        vad=all((root/"models/FireRedVAD-ONNX"/name).is_file() for name in ("cmvn.ark","fireredvad_stream_vad_with_cache.onnx"))
        return {"available": bool(compatible) and models and vad, "native_available":bool(compatible),"models_available":models,"vad_available":vad,"python_abi": abi, "root": str(root),
                "build_dir": str(selected),
                "extensions": [str(path) for path in compatible],
                "reason": f"未找到匹配 {abi} 的Confucius原生扩展" if not compatible else "Confucius目录缺少Q8模型或音频投影模型" if not models else "Confucius目录缺少FireRedVAD字幕组件" if not vad else ""}

    def load(self):
        with self.lock:
            if self.engine is not None:
                return self.engine
            status = self.available()
            if not status["available"]:
                raise RuntimeError(status["reason"])
            from ._vendor.confucius.native import NativeQ8Engine
            import torch
            root = Path(status["root"])
            build = Path(status["build_dir"])
            gpu_layers = -1 if torch.cuda.is_available() and configuration()["device"] != "cpu" else 0
            manifest = build / "manifest.json"
            if gpu_layers and manifest.is_file():
                description = json.loads(manifest.read_text(encoding="utf-8"))
                architectures = description.get("gpu_architectures") or ([int(description["sm"])] if description.get("sm") else [])
                capability = torch.cuda.get_device_capability()
                if architectures and capability[0]*10+capability[1] not in architectures:
                    gpu_layers = 0
            self.execution_device = "cuda" if gpu_layers else "cpu"
            self.engine = NativeQ8Engine(root / "models/Confucius4-R2T2-GGUF",
                                        build, gpu_layers=gpu_layers, hash_files=True)
            return self.engine

    def transcribe(self, filename, *, language=None, context="", hotwords="",
                   subtitle_timings=False, cancel_event=None, progress=None, unload_after=True):
        from .audio import read_audio
        from ._vendor.confucius.audio import to_mono_16k
        path = Path(filename).resolve(strict=True)
        samples, sample_rate = read_audio(path)
        pcm = to_mono_16k(samples, sample_rate)
        duration = len(pcm) / 16000
        if not np.any(pcm):
            return {"text": "", "language": "", "segments": [], "audio_seconds": duration,
                    "audio_samples_16k": len(pcm), "truncated": False, "mode_executed": "digital_silence", "status": "complete"}
        if duration < .1:
            raise ValueError("录音不足0.1秒，请选择更长的语音片段后再识别")
        if language in (None, "", "Auto", "AUTO"):
            language = None
        prompt = hotword_context(context, hotwords)
        started = time.perf_counter()
        with self.lock:
            engine = self.load()
            try:
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("转写已取消")
                if progress:
                    progress("transcribing", 0, "使用Confucius识别参考录音")
                if duration > 30 or subtitle_timings:
                    from ._vendor.confucius.segmented import SegmentedStream
                    from ._vendor.confucius.vad import FireRedOnnxVAD
                    root = Path(configuration()["asr_root"])
                    vad = FireRedOnnxVAD(root / "models/FireRedVAD-ONNX")
                    session = SegmentedStream(engine, language=language, context=prompt, offline=True, vad=vad)
                    for position in range(0, len(pcm), 640):
                        if cancel_event is not None and cancel_event.is_set():
                            raise RuntimeError("转写已取消")
                        session.feed(pcm[position:position + 640])
                        if progress and position % 16000 == 0:
                            progress("transcribing", position / len(pcm), "正在识别音频分段")
                    terminal = session.finish()
                    result = {"text": session.stable_text, "language": session.detected_language,
                              "segments": session.segments, "truncated": terminal.get("truncated", False),
                              "forced_boundaries": session.forced_boundaries,
                              "mode_executed": "segmented_offline"}
                else:
                    result = engine.transcribe(pcm, language=language, context=prompt)
                    result["segments"] = []
                    result["mode_executed"] = "offline"
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("转写已取消")
                result.update(audio_seconds=duration, audio_samples_16k=len(pcm),
                              seconds=time.perf_counter() - started, backend="confucius_native_q8",
                              execution_device=self.execution_device,
                              timings="vad_segments_approximate" if subtitle_timings else "none",
                              status="truncated" if result.get("truncated") else "requires_review" if result.get("forced_boundaries") else "complete")
                return result
            except Exception as error:
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("转写已取消") from error
                raise
            finally:
                if unload_after:
                    self.unload()

    def unload(self):
        with self.lock:
            if self.engine is not None:
                self.engine.close()
            self.engine = None
            gc.collect()

    def cancel(self):
        engine = self.engine
        if engine is not None:
            engine.request_cancel()


ASR = ConfuciusASR()
