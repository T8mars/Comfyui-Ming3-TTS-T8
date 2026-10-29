import sys
import types
from unittest.mock import Mock

import pytest
import torch


@pytest.mark.parametrize("cuda_available,device,uses_cuda", [
    (False, "cuda:0", False),
    (True, "cpu", False),
    (True, "cuda:0", True),
])
def test_asr_memory_preparation_matches_execution_device(monkeypatch, cuda_available, device, uses_cuda):
    from ming_t8 import comfy_residency, config

    memory = types.ModuleType("comfy.model_management")
    memory.free_memory = Mock()
    comfy = types.ModuleType("comfy")
    comfy.model_management = memory
    monkeypatch.setitem(sys.modules, "comfy", comfy)
    monkeypatch.setitem(sys.modules, "comfy.model_management", memory)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: cuda_available)
    monkeypatch.setattr(config, "configuration", lambda: {"device": device})
    release = Mock()
    unload = Mock()
    monkeypatch.setattr(comfy_residency, "release", release)
    monkeypatch.setattr(comfy_residency.MODEL_MANAGER, "unload", unload)

    comfy_residency.prepare_asr()

    release.assert_called_once_with()
    unload.assert_called_once_with()
    if uses_cuda:
        memory.free_memory.assert_called_once_with(4 * 1024**3, torch.device("cuda:0"))
    else:
        memory.free_memory.assert_not_called()
