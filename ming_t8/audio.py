from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid
from collections import OrderedDict
import threading

import numpy as np
import soundfile as sf

from .config import data_directory

_REFERENCE_CACHE=OrderedDict()
_REFERENCE_LOCK=threading.RLock()
_REFERENCE_BYTES=0


def find_ffmpeg():
    candidates = [Path(__file__).resolve().parents[1] / "components/ffmpeg/ffmpeg.exe",
                  Path("D:/ffmpeg/bin/ffmpeg.exe")]
    found = shutil.which("ffmpeg")
    return str(next((path for path in candidates if path.is_file()), found or ""))


def read_audio(filename):
    path = Path(filename).resolve(strict=True)
    try:
        samples, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    except (sf.LibsndfileError, RuntimeError):
        executable = find_ffmpeg()
        if not executable:
            raise ValueError("此音频格式需要FFmpeg，请使用WAV/FLAC，或安装随包提供的音频组件")
        target = data_directory("cache/audio") / (hashlib.sha256(path.read_bytes()).hexdigest() + ".wav")
        if not target.is_file():
            temporary = target.with_name(target.stem + "." + uuid.uuid4().hex + ".wav")
            try:
                subprocess.run([executable, "-v", "error", "-i", str(path), "-vn", "-map", "0:a:0",
                                "-c:a", "pcm_f32le", str(temporary)], check=True, capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                temporary.replace(target)
            except subprocess.CalledProcessError as error:
                raise ValueError("无法解码此音频，请检查文件是否完整并包含音轨") from error
            finally:
                temporary.unlink(missing_ok=True)
        samples, sample_rate = sf.read(str(target), dtype="float32", always_2d=True)
    if samples.size == 0 or not np.isfinite(samples).all():
        raise ValueError("录音为空，或包含无效的音频数值")
    return samples, int(sample_rate)


def inspect_audio(filename):
    samples, sample_rate = read_audio(filename)
    mono = samples.mean(axis=1)
    bins = np.array_split(mono, min(600, len(mono)))
    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(samples ** 2)))
    warnings = []
    if peak == 0:
        warnings.append("这段录音是全静音，请更换录音")
    elif rms < .001:
        warnings.append("录音音量较低，建议检查试听")
    if float(np.mean(np.abs(samples) >= .999)) > .001:
        warnings.append("录音可能有削波失真，建议更换更清晰的片段")
    return {"seconds": len(samples) / sample_rate, "sample_rate": sample_rate,
            "channels": samples.shape[1], "peak": peak, "rms": rms,
            "waveform": [float(np.max(np.abs(item))) for item in bins], "warnings": warnings}


def load_prompt_waveform(filename, target_sample_rate):
    # SoundFile decoding and the same Resample class preserve the released path,
    # including on newer torchaudio versions whose load() delegates to TorchCodec.
    import torch
    import torchaudio
    from .provenance import file_digest
    global _REFERENCE_BYTES
    key=(file_digest(filename),int(target_sample_rate))
    with _REFERENCE_LOCK:
        if key in _REFERENCE_CACHE:
            _REFERENCE_CACHE.move_to_end(key)
            return _REFERENCE_CACHE[key].clone()
    samples, rate = read_audio(filename)
    waveform = torch.from_numpy(samples.T.copy()).float().mean(dim=0, keepdim=True)
    if rate != target_sample_rate:
        waveform = torchaudio.transforms.Resample(rate, target_sample_rate)(waveform)
    size=waveform.numel()*waveform.element_size()
    if size<=64*1024**2:
        with _REFERENCE_LOCK:
            if key not in _REFERENCE_CACHE:
                _REFERENCE_CACHE[key]=waveform.clone();_REFERENCE_BYTES+=size
            while _REFERENCE_BYTES>128*1024**2 or len(_REFERENCE_CACHE)>64:
                _,old=_REFERENCE_CACHE.popitem(last=False)
                _REFERENCE_BYTES-=old.numel()*old.element_size()
    return waveform


def clear_reference_cache():
    global _REFERENCE_BYTES
    with _REFERENCE_LOCK:
        _REFERENCE_CACHE.clear();_REFERENCE_BYTES=0


class CachedSpeakerExtractor:
    def __init__(self,extractor,max_entries=64):
        self.extractor=extractor
        self.max_entries=max_entries
        self.cache=OrderedDict()

    def __call__(self,waveform,**kwargs):
        key=hashlib.sha256(waveform.detach().cpu().contiguous().numpy().tobytes()).hexdigest()
        if key not in self.cache:
            self.cache[key]=self.extractor(waveform,**kwargs).detach().cpu().clone()
            while len(self.cache)>self.max_entries:self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        return self.cache[key].clone()


def save_waveform(filename,waveform,sample_rate):
    target=Path(filename)
    target.parent.mkdir(parents=True,exist_ok=True)
    value=waveform.detach().cpu().float()
    if value.ndim==3:value=value.squeeze(0)
    if value.ndim==1:value=value.unsqueeze(0)
    sf.write(str(target),value.numpy().T,int(sample_rate),subtype="FLOAT")


def prepare_reference(filename, start=0.0, end=None):
    samples, sample_rate = read_audio(filename)
    duration = len(samples) / sample_rate
    end = duration if end is None else float(end)
    if not 0 <= float(start) < end <= duration + 1 / sample_rate:
        raise ValueError("裁切范围无效，请确保开始时间早于结束时间，并位于录音长度之内")
    segment = samples[round(float(start) * sample_rate):round(end * sample_rate)]
    if not np.any(segment):
        raise ValueError("选中的参考片段是全静音")
    signature = hashlib.sha256(segment.tobytes() + str(sample_rate).encode()).hexdigest()
    destination = data_directory("references") / f"{signature}.wav"
    if not destination.is_file():
        sf.write(str(destination), segment, sample_rate, subtype="FLOAT")
    return {"path": str(destination), "sha256": signature, "start": float(start), "end": end,
            **inspect_audio(destination)}


def export_audio(source, kind):
    if kind not in ("wav", "flac", "mp3"):
        raise ValueError("不支持的音频导出格式")
    source = Path(source)
    if kind == "wav":
        return source
    target = source.with_suffix("." + kind)
    if target.is_file():
        return target
    import uuid
    temporary = target.with_name(f".{target.stem}-{uuid.uuid4().hex}{target.suffix}")
    try:
        if kind == "flac":
            samples, rate = sf.read(str(source), always_2d=True)
            sf.write(str(temporary), samples, rate, subtype="PCM_24")
        else:
            executable = find_ffmpeg()
            if not executable:
                raise ValueError("MP3导出需要FFmpeg组件")
            subprocess.run([executable, "-nostdin", "-v", "error", "-i", str(source), "-codec:a", "libmp3lame", "-q:a", "2", str(temporary)],
                           check=True, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
