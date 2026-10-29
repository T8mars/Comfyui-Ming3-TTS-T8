"""Single-GPU durable job queue; the worker calls native Python engines directly."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import queue
import threading
import time
import traceback
from copy import deepcopy

import numpy as np
import soundfile as sf

from .contracts import TaskRequest
from .config import data_directory
from .storage import Store

TERMINAL = {"complete", "needs_review", "failed", "cancelled", "interrupted"}


def audio_digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            value.update(block)
    return value.hexdigest()


def job_error_message(error):
    message = str(error)
    if type(error).__name__ == "OutOfMemoryError" or "cuda out of memory" in message.lower():
        return ("显存不足。请关闭其他占用显存的程序，释放模型后重试；"
                "也可减少单次文本长度或角色数量。已完成片段仍保留，可继续重试。")
    return message


class JobQueue:
    def __init__(self, store=None):
        self.store = store or Store()
        self.pending = queue.Queue()
        self.cancel_events = {}
        self.active = None
        self.lock = threading.RLock()
        self.stopping = False
        # Recover persisted queued work; an interrupted native call is never assumed complete.
        restored = self.store.list_by_status("job", ("queued", "running", "cancelling"))
        for job in restored:
            if job["status"] in ("running", "cancelling"):
                self.store.update("job", job["id"], status="interrupted", message="上次运行被中断，可保留已完成片段后重试")
            elif job["status"] == "queued":
                self.cancel_events[job["id"]] = threading.Event()
                self.pending.put(job["id"])
        self.worker = threading.Thread(target=self._work, name="ming-native-jobs", daemon=True)
        self.worker.start()

    def submit(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("任务设置必须是对象")
        operation = payload.get("operation", "generate")
        if operation not in ("generate", "batch", "transcribe"):
            raise ValueError("不支持的任务类型")
        if operation == "generate":
            TaskRequest.from_dict(payload.get("request"))
        elif operation == "batch":
            if not isinstance(payload.get("segments"), list) or not 1 <= len(payload["segments"]) <= 1000:
                raise ValueError("批量任务必须包含1到1000个片段")
            for segment in payload["segments"]:
                if not isinstance(segment, dict):
                    raise ValueError("每个批量片段必须是对象")
                TaskRequest.from_dict(segment.get("request"))
                pause = segment.get("pause_ms", 250)
                if isinstance(pause, bool) or not isinstance(pause, (int, float)) or not 0 <= pause <= 60000:
                    raise ValueError("段落停顿必须在0到60000毫秒之间")
        else:
            if not isinstance(payload.get("audio_path"), str) or not Path(payload["audio_path"]).is_file():
                raise ValueError("请先上传或选择参考录音")
        job = self.store.put("job", {"payload": payload, "status": "queued", "progress": 0,
                                    "phase": "queued", "message": "已加入队列", "created_at": time.time(),
                                    "result": None, "chunks": [], "completed_segments": []})
        self.cancel_events[job["id"]] = threading.Event()
        self.pending.put(job["id"])
        return job

    def cancel(self, identifier):
        with self.lock:
            job = self.store.get("job", identifier)
            if job["status"] in TERMINAL:
                return job
            self.cancel_events.setdefault(identifier, threading.Event()).set()
            if self.active == identifier:
                self.store.update("job", identifier, status="cancelling", message="已请求取消，正在结束当前计算")
                from .engine import MODEL_MANAGER
                from .asr import ASR
                if MODEL_MANAGER.engine is not None:
                    MODEL_MANAGER.engine.cancel()
                ASR.cancel()
                return self.store.get("job", identifier)
            return self.store.update("job", identifier, status="cancelled", message="已取消排队任务")

    def retry(self, identifier):
        previous = self.store.get("job", identifier)
        if previous["status"] not in TERMINAL:
            raise ValueError("请先等待当前任务结束或取消")
        payload = deepcopy(previous["payload"])
        payload.pop("retry_of", None)
        if previous["status"] != "complete":
            payload["retry_of"] = identifier
        else:
            for segment in payload.get("segments", []):
                segment.pop("reuse_from", None)
        return self.submit(payload)

    def _work(self):
        while not self.stopping:
            try:
                identifier = self.pending.get(timeout=.5)
            except queue.Empty:
                continue
            try:
                with self.lock:
                    job = self.store.get("job", identifier)
                    if job["status"] != "queued":
                        continue
                    self.active = identifier
                    self.store.update("job", identifier, status="running", started_at=time.time())
                result = self._execute(identifier, job["payload"])
                with self.lock:
                    if self.cancel_events[identifier].is_set():
                        self.store.update("job", identifier, status="cancelled", message="任务已取消，已完成片段仍可下载", result=result)
                    else:
                        review = bool(result.get("truncated")) or result.get("status") == "requires_review"
                        self.store.update("job", identifier, status="needs_review" if review else "complete", progress=1,
                                          phase="complete", message=("转写完成，请校对识别结果" if result.get("status") == "requires_review" else "已达到长度上限，请检查尾句") if review else "任务完成", result=result,
                                          finished_at=time.time())
            except Exception as error:
                folder = data_directory("jobs") / identifier
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
                with self.lock:
                    cancelled = self.cancel_events.get(identifier, threading.Event()).is_set()
                    self.store.update("job", identifier, status="cancelled" if cancelled else "failed",
                                      message="任务已取消，已完成片段仍保留" if cancelled else job_error_message(error), finished_at=time.time())
            finally:
                with self.lock:
                    self.active = None
                self.pending.task_done()

    def _completed_audio(self, identifier, index, identity, sample_rate):
        """A take is an optional cache, never a prerequisite for a new generation."""
        if not isinstance(identifier, str) or not identifier.isalnum() or isinstance(index, bool):
            return None
        try:
            records = self.store.get("job", identifier).get("completed_segments", [])
            index = int(index)
            if not 0 <= index < len(records):
                return None
            record = records[index]
            if record.get("identity") != identity or record.get("truncated") or not record.get("audio_sha256"):
                return None
            folder = (data_directory("jobs") / identifier).resolve()
            source = (folder / record["file"]).resolve()
            if source.parent != folder or not source.is_file() or audio_digest(source) != record["audio_sha256"]:
                return None
            samples, rate = sf.read(str(source), dtype="float32")
            metrics = record["metrics"]
            if rate != sample_rate or samples.ndim != 1 or not samples.size or not np.isfinite(samples).all() or not isinstance(metrics, dict):
                return None
            return samples, metrics
        except (KeyError, ValueError, TypeError, OSError, RuntimeError):
            return None

    def _execute(self, identifier, payload):
        started = time.monotonic()
        from .engine import MODEL_MANAGER, GenerationCancelled
        from .asr import ASR
        folder = data_directory("jobs") / identifier
        folder.mkdir(parents=True, exist_ok=True)
        cancel = self.cancel_events[identifier]
        last_update = [0.0]

        def progress(phase, fraction, message):
            if cancel.is_set():
                raise GenerationCancelled("任务已取消")
            now = time.monotonic()
            if now - last_update[0] > .15 or fraction >= 1:
                self.store.update("job", identifier, phase=phase, progress=max(0, min(float(fraction), 1)), message=message)
                last_update[0] = now

        if payload.get("operation") == "transcribe":
            MODEL_MANAGER.unload()
            result = ASR.transcribe(payload["audio_path"], language=payload.get("language"),
                                    context=payload.get("context", ""), hotwords=payload.get("hotwords", ""),
                                    subtitle_timings=payload.get("subtitle_timings", False),
                                    cancel_event=cancel, progress=progress, unload_after=True)
            (folder / "transcript.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            (folder / "transcript.txt").write_text(result["text"], encoding="utf-8")
            result["transcript_file"] = "transcript.txt"
            result["seconds"] = time.monotonic() - started
            return result
        ASR.unload()
        engine = MODEL_MANAGER.get(payload.get("model_path"), payload.get("assets_path"),
                                   payload.get("device"), progress=progress)
        segments = payload.get("segments") if payload.get("operation") == "batch" else [{"request": payload["request"], "pause_ms": 0}]
        waveforms, records, metrics = [], [], []
        cursor, chunk_number = 0, 0
        for index, segment in enumerate(segments):
            if cancel.is_set():
                raise GenerationCancelled("任务已取消")
            request = TaskRequest.from_dict(segment["request"])
            from .provenance import generation_identity
            identity = generation_identity(request, {**engine.identity, "execution_profile": engine.execution_profile})
            segment_path = folder / f"segment-{index+1:04d}.wav"

            def chunk_callback(waveform, sample_rate, final):
                nonlocal chunk_number
                chunk_number += 1
                filename = f"stream-{chunk_number:05d}.wav"
                sf.write(str(folder / filename), waveform.reshape(-1).numpy(), sample_rate, subtype="FLOAT")
                current = self.store.get("job", identifier)
                self.store.update("job", identifier, chunks=[*current["chunks"], filename])

            def segment_progress(phase, fraction, message):
                progress(phase, (index + fraction) / len(segments),
                         f"片段 {index+1}/{len(segments)} · {message}" if len(segments) > 1 else message)

            # Retry can reuse exact completed segments, but never a partial or truncated file.
            reused = False
            take = segment.get("reuse_from")
            take = take if isinstance(take, dict) else {}
            previous_id = take.get("job_id") or payload.get("retry_of")
            if previous_id:
                cached = self._completed_audio(previous_id, take.get("segment_index", 0) if take else index, identity, engine.sample_rate)
                if cached is not None:
                    waveform, measurement = cached
                    sf.write(str(segment_path), waveform, engine.sample_rate, subtype="FLOAT")
                    reused = True
            if not reused:
                output, measurement = engine.generate(request, output_path=str(segment_path), progress=segment_progress,
                                                       audio_callback=chunk_callback if payload.get("streaming", False) else None)
                waveform = output.waveform.detach().cpu().float().reshape(-1).numpy()
            elif payload.get("streaming", False):
                import torch
                chunk_callback(torch.from_numpy(waveform.copy()).reshape(1,1,-1),engine.sample_rate,False)
            rate = engine.sample_rate
            start_ms, end_ms = round(cursor * 1000 / rate), round((cursor + len(waveform)) * 1000 / rate)
            record = {"file": segment_path.name, "request": request.to_dict(), "metrics": measurement,
                      "audio_sha256": audio_digest(segment_path),
                      "start_ms": start_ms, "end_ms": end_ms, "text": request.text,
                      "truncated": measurement.get("truncated", False), "reused": reused, "identity": identity}
            records.append(record)
            waveforms.append(waveform)
            cursor += len(waveform)
            pause = round(float(segment.get("pause_ms", 0)) * rate / 1000) if index + 1 < len(segments) else 0
            if pause:
                waveforms.append(np.zeros(pause, dtype=np.float32))
                cursor += pause
                if payload.get("streaming",False):
                    import torch
                    chunk_callback(torch.zeros(1,1,pause),rate,False)
            metrics.append(measurement)
            self.store.update("job", identifier, completed_segments=records)
        combined = np.concatenate(waveforms)
        sf.write(str(folder / "output.wav"), combined, engine.sample_rate, subtype="PCM_24")
        result = {"audio_file": "output.wav", "sample_rate": engine.sample_rate, "audio_seconds": len(combined) / engine.sample_rate,
                  "waveform": [float(np.max(np.abs(chunk))) for chunk in np.array_split(combined,min(256,len(combined)))],
                  "segments": records, "metrics": metrics, "truncated": any(item["truncated"] for item in records),
                  "timings": "generation_segment_boundaries", "streaming": bool(payload.get("streaming")),
                  "model": str(engine.model_path), "load_info": engine.load_info,
                  "seconds": time.monotonic() - started}
        (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def shutdown(self):
        self.stopping = True
        if self.active:
            self.cancel(self.active)
        self.worker.join(timeout=20)
        if not self.worker.is_alive():
            from .engine import MODEL_MANAGER
            from .asr import ASR
            MODEL_MANAGER.unload()
            ASR.unload()
            self.store.close()
