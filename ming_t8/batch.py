"""Validated batch import shared by studio and Comfy nodes."""
from __future__ import annotations

import csv
from dataclasses import fields
import io
import json
import math

from .contracts import TaskRequest
from .text import split_long_text


def preview_batch(template, text, format="long", max_units=120, pause_ms=250):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("请先填写文字或选择批量文件")
    if len(text) > 2_000_000:
        raise ValueError("批量文本超过200万字符，请分批处理")
    if not isinstance(pause_ms, (int, float)) or not math.isfinite(pause_ms) or not 0 <= pause_ms <= 60000:
        raise ValueError("段落停顿必须在0到60000毫秒之间")
    text = text.lstrip("\ufeff")
    if format == "long":
        rows = [{"text": item} for item in split_long_text(text, max_units)]
    elif format == "txt":
        rows = [{"text": line.strip()} for line in text.splitlines() if line.strip()]
    elif format in ("csv", "tsv"):
        reader = csv.DictReader(io.StringIO(text), delimiter="\t" if format == "tsv" else ",")
        if "text" not in (reader.fieldnames or []):
            raise ValueError("CSV/TSV首行需包含text列，可增加task、ip、seed、pause_ms等列")
        rows = list(reader)
    elif format == "json":
        value = json.loads(text)
        rows = value.get("segments") if isinstance(value, dict) else value
        if not isinstance(rows, list):
            raise ValueError("JSON需为片段数组，或包含segments数组的对象")
        rows = [{"text": item} if isinstance(item, str) else item for item in rows]
    else:
        raise ValueError("支持TXT、CSV、TSV、JSON或长文分段")
    if not 1 <= len(rows) <= 1000:
        raise ValueError("一次批量需要1到1000个片段")
    names = {field.name for field in fields(TaskRequest)}
    numeric_int = {"seed", "flow_steps", "min_decode_steps", "max_decode_steps", "min_generation_frames", "max_generation_frames", "log_every_n_steps"}
    numeric_float = {"cfg_scale", "sigma", "temperature", "stop_threshold"}
    segments = []
    for index, row in enumerate(rows):
        try:
            if not isinstance(row, dict):
                raise ValueError("每个片段需为文字或对象")
            overrides = row.get("request", {key: value for key, value in row.items() if key != "pause_ms"})
            if not isinstance(overrides, dict) or set(overrides) - names:
                raise ValueError("片段含有不支持的生成字段")
            base = template
            if overrides.get("task",template.get("task")) != template.get("task"):
                base = {key:value for key,value in template.items() if key in numeric_int | numeric_float}
            values = {**base, **{key: value for key, value in overrides.items() if value != ""}}
            for key in numeric_int | numeric_float:
                if isinstance(values.get(key), str):
                    values[key] = int(values[key]) if key in numeric_int else float(values[key])
            request = TaskRequest.from_dict(values)
            pause = float(row.get("pause_ms", pause_ms))
            if not math.isfinite(pause) or not 0 <= pause <= 60000:
                raise ValueError("停顿需在0到60000毫秒之间")
            segments.append({"request": request.to_dict(), "pause_ms": pause})
        except (ValueError, TypeError) as error:
            raise ValueError(f"第{index+1}个片段：{error}") from error
    return {"segments": segments, "count": len(segments)}
