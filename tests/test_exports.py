import pytest

from ming_t8.exports import subtitles


def generation_result():
    return {
        "timings": "generation_segment_boundaries",
        "segments": [
            {"request": {"task": "ip"}, "start_ms": 0, "end_ms": 1000, "text": "First."},
            {"request": {"task": "ip"}, "start_ms": 1500, "end_ms": 2500, "text": "Second."},
        ],
    }


@pytest.mark.parametrize("result_truncated,segment_truncated", [(True, False), (False, True)])
def test_generation_subtitles_reject_incomplete_audio(result_truncated, segment_truncated):
    result = generation_result()
    result["truncated"] = result_truncated
    result["segments"][0]["truncated"] = segment_truncated
    with pytest.raises(ValueError, match="截断"):
        subtitles(result)


def test_complete_generation_subtitles_preserve_actual_segment_timing():
    result = generation_result()
    assert "00:00:01,500 --> 00:00:02,500\nSecond." in subtitles(result)
    assert subtitles(result, "vtt").startswith("WEBVTT\n")
    result["segments"][0]["request"]["task"] = "podcast"
    with pytest.raises(ValueError, match="Podcast"):
        subtitles(result)
