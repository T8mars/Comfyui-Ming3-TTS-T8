import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="The shipped launchers target Windows")


def launcher_fixture(tmp_path):
    folder = tmp_path / "program with spaces"
    (folder / "scripts").mkdir(parents=True)
    for name in ("启动工作台.cmd", "一键更新.cmd"):
        (folder / name).write_bytes((ROOT / name).read_bytes())
    helper = """import json,os,sys
from pathlib import Path
with Path(os.environ['MING_TEST_LOG']).open('a',encoding='utf-8') as output:
 output.write(json.dumps({'script':Path(__file__).name,'args':sys.argv[1:],'data':os.environ.get('MING_T8_DATA')})+'\\n')
if Path(__file__).name=='update_program.py':sys.exit(int(os.environ.get('MING_TEST_UPDATE_EXIT','0')))
"""
    (folder / "scripts/update_program.py").write_text(helper, encoding="utf-8")
    (folder / "studio.py").write_text(helper, encoding="utf-8")
    log = tmp_path / "calls.jsonl"
    environment = {**os.environ, "MING_PYTHON": sys.executable, "MING_TEST_LOG": str(log), "MING_T8_DATA": str(tmp_path / "preserved data")}
    return folder, log, environment


def run_launcher(folder, name, environment, *arguments):
    return subprocess.run(["cmd.exe", "/d", "/c", "call", str(folder / name), *arguments],
                          cwd=folder, env=environment, input=b"\r\n", capture_output=True, timeout=15)


def test_launcher_applies_update_then_starts_studio_and_preserves_data_override(tmp_path):
    folder, log, environment = launcher_fixture(tmp_path)
    result = run_launcher(folder, "启动工作台.cmd", environment, "--no-browser")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert [item["script"] for item in calls] == ["update_program.py", "studio.py"]
    assert calls[0]["args"] == ["--apply-pending"] and calls[1]["args"] == ["--no-browser"]
    assert all(item["data"] == environment["MING_T8_DATA"] for item in calls)


def test_failed_pending_update_does_not_start_studio(tmp_path):
    folder, log, environment = launcher_fixture(tmp_path)
    result = run_launcher(folder, "启动工作台.cmd", {**environment, "MING_TEST_UPDATE_EXIT": "5"})
    assert result.returncode != 0
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert [item["script"] for item in calls] == ["update_program.py"]


def test_one_click_update_runs_only_the_updater(tmp_path):
    folder, log, environment = launcher_fixture(tmp_path)
    result = run_launcher(folder, "一键更新.cmd", environment)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(calls) == 1 and calls[0]["script"] == "update_program.py" and calls[0]["args"] == ["--update"]
