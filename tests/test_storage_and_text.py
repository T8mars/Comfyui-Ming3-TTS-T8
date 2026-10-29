import pytest
from ming_t8.storage import Store
from ming_t8.text import split_long_text


def test_local_records_survive_restart_and_partial_updates(tmp_path):
    path = tmp_path / "中文 目录" / "studio.db"
    store = Store(path)
    job = store.put("job", {"status": "queued", "request": {"text": "你好"}})
    store.update("job", job["id"], status="running", progress=.25)
    store.close()
    restored = Store(path)
    assert restored.get("job", job["id"])["request"]["text"] == "你好"
    assert restored.get("job", job["id"])["progress"] == .25
    restored.delete("job", job["id"])
    with pytest.raises(KeyError):
        restored.get("job", job["id"])
    restored.close()


def test_long_text_preserves_tags_and_punctuation():
    text = "[Laughter]" + "这是一段需要完整保留的中文句子。" * 12
    segments = split_long_text(text, 40)
    assert "".join(segments) == text
    assert "[Laughter]" in segments[0]
    assert len(segments) > 2


def test_every_node_task_builds_the_same_core_request():
    import nodes
    node = nodes.MingT8Task()
    reference = {"path": "a.wav", "text": "参考文本"}
    values = {"seed": {}, "multilingual": {"language": "Japanese"}, "paralinguistic": {},
              "basic": {}, "emotion": {}, "dialect": {}, "freeform": {"instruction": "轻声叙述"},
              "voice_design": {"style": "清晰女声"}, "ip": {},
              "podcast": {"text": "speaker_1: 你好\nspeaker_2: 你好", "speakers": [reference, reference]}}
    for task, options in values.items():
        arguments = {"task": task, "text": "你好", "reference": reference, **options}
        request, = node.build(**arguments)
        assert request["task"] == task
