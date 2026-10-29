from concurrent.futures import ThreadPoolExecutor
import json
import threading

from ming_t8 import config


def test_program_defaults_are_relative_and_do_not_use_a_development_drive(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("MING_T8_DATA", raising=False)
    assert config.configuration()["data_root"] == str((tmp_path / "data").resolve())


def test_concurrent_settings_updates_preserve_all_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    path = tmp_path / "settings.local.json"
    changes = [{"device": "cpu"}, {"native_kernels": "portable"},
               {"attention_backend": "auto"}, {"cuda_graphs": False}]
    for _ in range(5):
        path.write_text(json.dumps({"retained": "unchanged"}))
        barrier = threading.Barrier(len(changes))

        def update(values):
            barrier.wait(timeout=5)
            return config.save_configuration(values)

        with ThreadPoolExecutor(len(changes)) as pool:
            results = list(pool.map(update, changes))
        expected = {key: value for change in changes for key, value in change.items()}
        assert json.loads(path.read_text()) == {"retained": "unchanged", **expected}
        assert all(result["retained"] == "unchanged" for result in results)
