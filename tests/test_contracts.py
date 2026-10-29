import pytest
from ming_t8.contracts import TaskRequest, capabilities


def test_all_ten_released_tasks_are_reachable():
    common = {"text": "测试语音。"}
    references = {"prompt_wav": "reference.wav"}
    transcribed = {**references, "prompt_text": "参考录音。", "target_language": "Chinese"}
    cases = {
        "seed": transcribed,
        "multilingual": {**transcribed, "target_language": "Japanese"},
        "paralinguistic": {**transcribed, "text": "[Laughter]你好。"},
        "basic": {**references, "speed": "中速", "pitch": "中", "volume": "中"},
        "emotion": {**references, "emotion": "高兴"},
        "dialect": {**references, "dialect": "广粤话"},
        "freeform": {"instruction": "温暖自然地讲故事"},
        "voice_design": {"style": "年轻清晰的女声"},
        "ip": {"ip": "灵小柔"},
        "podcast": {"text": "speaker_1: 你好。\nspeaker_2: 今天很好。",
                    "prompt_wav": ["a.wav", "b.wav"], "prompt_text": ["甲", "乙"]},
    }
    assert set(cases) == {item["id"] for item in capabilities()}
    for task, arguments in cases.items():
        request = TaskRequest.from_dict({"task": task, **common, **arguments})
        assert request.validate().task == task


@pytest.mark.parametrize("arguments", [
    {"task": "seed", "prompt_wav": "a.wav", "target_language": "Chinese"},
    {"task": "multilingual", "prompt_wav": "a.wav", "prompt_text": "参考", "target_language": "Chinese"},
    {"task": "paralinguistic", "prompt_wav": "a.wav", "prompt_text": "参考", "target_language": "German"},
    {"task": "basic", "prompt_wav": "a.wav", "speed": "超快", "pitch": "中", "volume": "中"},
    {"task": "emotion", "prompt_wav": "a.wav", "emotion": "不存在的情绪"},
    {"task": "dialect", "prompt_wav": "a.wav", "dialect": "不存在的方言"},
    {"task": "freeform", "instruction": "轻声", "prompt_text": "不适用的转录"},
    {"task": "voice_design", "style": "清晰女声", "prompt_wav": "a.wav"},
    {"task": "ip", "ip": "灵小柔", "prompt_wav": "a.wav"},
    {"task": "podcast", "text": "speaker_1: 你好", "prompt_wav": ["a.wav"], "prompt_text": ["参考"]},
])
def test_every_task_rejects_incomplete_or_inapplicable_conditioning(arguments):
    with pytest.raises(ValueError):
        TaskRequest.from_dict({"text": "测试语音。", **arguments})


@pytest.mark.parametrize("change", [
    {"emotion": "高兴"}, {"prompt_wav": "x.wav"}, {"target_language": "Chinese"},
    {"seed": -1}, {"temperature": float("nan")}, {"flow_steps": 0},
    {"min_generation_frames": 8, "max_generation_frames": 600},
])
def test_design_does_not_accept_hidden_parameters_from_other_modes(change):
    with pytest.raises(ValueError):
        TaskRequest.from_dict({"task": "voice_design", "text": "你好", "style": "清晰女声", **change})


def test_freeform_optional_reference_and_forbidden_transcript():
    base = {"task": "freeform", "text": "你好", "instruction": "轻声说话"}
    assert TaskRequest.from_dict(base).resolve().conditioning == "masked_speaker"
    assert TaskRequest.from_dict({**base, "prompt_wav": "a.wav"}).resolve().conditioning == "speaker_only"
    with pytest.raises(ValueError):
        TaskRequest.from_dict({**base, "prompt_text": "不该传入"})


def test_podcast_rejects_missing_role_and_wrong_budget_units():
    base = {"task": "podcast", "text": "speaker_1: 甲\nspeaker_2: 乙",
            "prompt_wav": ["a.wav", "b.wav"], "prompt_text": ["甲", "乙"]}
    with pytest.raises(ValueError):
        TaskRequest.from_dict({**base, "max_decode_steps": 100})
    with pytest.raises(ValueError):
        TaskRequest.from_dict({**base, "text": "speaker_3: 错误角色"})
    assert TaskRequest.from_dict({**base, "min_generation_frames": 8, "max_generation_frames": 600})
