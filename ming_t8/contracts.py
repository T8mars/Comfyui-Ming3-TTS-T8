"""Versioned, UI-independent requests for every released Ming Tiny task."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import math
from typing import Any

from ._vendor.ming_tiny.task_protocol import resolve_task_request, TASK_SPECS

TASK_LABELS = {
    "seed": "中英文声音克隆", "multilingual": "多语种克隆",
    "paralinguistic": "笑声与语气标签", "podcast": "多人联合对话",
    "basic": "语速、音高与音量", "emotion": "情绪配音", "dialect": "方言配音",
    "freeform": "自由指令", "voice_design": "文字设计声音", "ip": "内置音色",
}


@dataclass(frozen=True)
class TaskRequest:
    task: str
    text: str
    prompt_wav: str | list[str] | None = None
    prompt_text: str | list[str] | None = None
    target_language: str | None = None
    instruction: str | None = None
    dialect: str | None = None
    emotion: str | None = None
    style: str | None = None
    speed: str | None = None
    pitch: str | None = None
    volume: str | None = None
    ip: str | None = None
    seed: int | None = None
    cfg_scale: float = 2.0
    flow_steps: int = 10
    sigma: float = .25
    temperature: float = 0.0
    min_decode_steps: int | None = None
    max_decode_steps: int | None = None
    stop_threshold: float | None = None
    min_generation_frames: int | None = None
    max_generation_frames: int | None = None
    log_every_n_steps: int = 0

    @classmethod
    def from_dict(cls, value: dict[str, Any]):
        if not isinstance(value, dict):
            raise ValueError("生成设置必须是对象")
        unknown = set(value) - {item.name for item in fields(cls)}
        if unknown:
            raise ValueError(f"不支持的生成参数：{', '.join(sorted(unknown))}")
        try:
            request = cls(**value)
        except TypeError as error:
            raise ValueError("请提供有效的task任务类型与text正文") from error
        request.validate()
        return request

    def resolve(self):
        arguments = {name: getattr(self, name) for name in (
            "text", "prompt_wav", "prompt_text", "target_language", "instruction",
            "dialect", "emotion", "style", "speed", "pitch", "volume", "ip",
        )}
        return resolve_task_request(self.task, **arguments)

    def validate(self):
        resolved = self.resolve()
        if self.seed is not None and (isinstance(self.seed, bool) or not isinstance(self.seed, int)
                                      or not 0 <= self.seed <= 2**64 - 1):
            raise ValueError("随机种子必须是0到2^64-1之间的整数")
        for name in ("cfg_scale", "temperature", "sigma"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} 必须是非负有限数值")
        if isinstance(self.flow_steps, bool) or not isinstance(self.flow_steps, int) or not 1 <= self.flow_steps <= 128:
            raise ValueError("Flow步数必须是1到128之间的整数")
        if self.stop_threshold is not None:
            value=self.stop_threshold
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=1:
                raise ValueError("停止阈值必须是0到1之间的有限数值")
        for name in ("min_decode_steps", "max_decode_steps", "min_generation_frames", "max_generation_frames", "log_every_n_steps"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} 必须是非负整数")
        if resolved.task == "podcast":
            if self.min_decode_steps is not None or self.max_decode_steps is not None:
                raise ValueError("多人联合对话使用generation frames，请不要传decode steps")
            low, high = self.min_generation_frames, self.max_generation_frames
            if (low is None) != (high is None):
                raise ValueError("多人对话的最小和最大帧数必须一起设置")
            if low is not None and not 8 <= low <= high <= 600:
                raise ValueError("多人对话帧数必须满足8≤最小值≤最大值≤600")
        elif self.min_generation_frames is not None or self.max_generation_frames is not None:
            raise ValueError("generation frames仅适用于多人联合对话")
        if self.max_decode_steps is not None:
            minimum = 13 if self.min_decode_steps is None else self.min_decode_steps
            if not 1 <= self.max_decode_steps <= 16384 or minimum > self.max_decode_steps:
                raise ValueError("最大生成步数必须不小于最小生成步数，并在1到16384之间")
        elif resolved.task!="podcast" and self.min_decode_steps is not None and self.min_decode_steps>250:
            raise ValueError("最小步数超过默认上限250时，请同时增大最大步数")
        return resolved

    def to_dict(self):
        return asdict(self)

    def api_arguments(self):
        self.validate()
        return self.to_dict()


def capabilities():
    return [{"id": name, "label": TASK_LABELS[name], "reference": spec.reference_count,
             "transcript": spec.prompt_text_mode, "controls": spec.instruction_kind,
             "languages": sorted(spec.allowed_languages or [])}
            for name, spec in TASK_SPECS.items()]
