"""Subtitle export without fabricated word alignment."""
from ._vendor.confucius.subtitles import build_subtitles, render_subtitle, wrap_text


def subtitles(result, kind="srt"):
    if result.get("timings") == "generation_segment_boundaries":
        segments = result.get("segments", [])
        if any(item["request"]["task"] == "podcast" for item in segments):
            raise ValueError("联合Podcast没有逐句对齐时间，请使用Confucius分段转写后导出字幕")
        document = {"cues": [{"start_ms": item["start_ms"], "end_ms": item["end_ms"],
                               "lines": wrap_text(item["text"])} for item in segments]}
    else:
        document = build_subtitles(result)
    content = render_subtitle(document, kind)
    if not content.strip():
        raise ValueError("没有可导出的字幕，请先识别有语音的音频")
    return content
