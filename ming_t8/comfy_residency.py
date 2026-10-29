"""Generic Comfy memory cooperation; Ming inference remains our own engine."""
from __future__ import annotations

import threading
import sys
from contextlib import contextmanager

import torch

from .engine import MODEL_MANAGER

_PATCHER = None
_LOCK = threading.RLock()


def check_host_capabilities(memory, patcher):
    required = ("free_memory", "load_models_gpu", "processing_interrupted")
    missing = [f"model_management.{name}" for name in required if not callable(getattr(memory, name, None))]
    if not hasattr(memory, "current_loaded_models"):
        missing.append("model_management.current_loaded_models")
    if not isinstance(patcher, type):
        missing.append("model_patcher.ModelPatcher")
    if missing:
        raise RuntimeError("当前ComfyUI缺少本节点需要的通用接口：" + "、".join(missing)
                           + "。请使用节点说明中记录的已验证版本或更新的兼容版本。")


def release():
    global _PATCHER
    with _LOCK:
        if _PATCHER is None:
            return
        import comfy.model_management as memory
        for loaded in list(memory.current_loaded_models):
            if loaded.model is _PATCHER:
                loaded.model_unload()
                memory.current_loaded_models.remove(loaded)
        _PATCHER = None


def get_engine(**handle):
    global _PATCHER
    try:
        import comfy.model_management as memory
        from comfy.model_patcher import ModelPatcher
    except ImportError as error:
        if error.name and error.name.split(".")[0] == "comfy":
            return MODEL_MANAGER.get(**handle)
        raise RuntimeError(f"ComfyUI通用显存组件无法导入，请检查宿主依赖：{error}") from error
    check_host_capabilities(memory, ModelPatcher)
    with _LOCK:
        settings_key = MODEL_MANAGER.request_key(**handle)
        if _PATCHER is not None and (_PATCHER.engine.closed or _PATCHER.handle_key != settings_key):
            release()
        if _PATCHER is None:
            device = torch.device(handle.get("device", "cuda:0"))
            if device.type == "cuda":
                # First load must also leave space for quantized prefill and AudioVAE.
                memory.free_memory(14 * 1024**3, device)
            engine = MODEL_MANAGER.get(**handle)

            class NativeResidency(ModelPatcher):
                def __init__(self):
                    super().__init__(engine.model, engine.device, torch.device("cpu"),
                                     size=sum(t.numel() * t.element_size() for t in engine.model.state_dict().values()))
                    self.engine = engine
                    self.handle_key = settings_key
                    self.resident_device = engine.device
                    self.resident_bytes = self.size if engine.device.type == "cuda" else 0

                def current_loaded_device(self):
                    return self.resident_device

                def loaded_size(self):
                    return self.resident_bytes

                def model_dtype(self):
                    return torch.bfloat16

                def model_patches_to(self, device):
                    # Never apply a blanket dtype conversion to FP32 recurrent state.
                    return None

                def partially_load(self, device_to, extra_memory=0, force_patch_weights=False):
                    if self.engine.closed or sys.is_finalizing():
                        self.resident_bytes = 0
                        return 0
                    if self.resident_device == device_to:
                        return 0
                    before = self.resident_bytes
                    with self.engine.lock:
                        if torch.device(device_to).type != "cuda" and hasattr(self.engine,"clear_acceleration_caches"):
                            self.engine.clear_acceleration_caches()
                        self.model.to(device=device_to)
                        self.resident_device = torch.device(device_to)
                        self.resident_bytes = self.size if self.resident_device.type == "cuda" else 0
                    return self.resident_bytes - before

                def partially_unload(self, device_to, memory_to_free=0, force_patch_weights=False):
                    before = self.resident_bytes
                    self.partially_load(device_to)
                    return before - self.resident_bytes

                def detach(self, unpatch_all=True):
                    self.partially_load(self.offload_device)
                    return self.model

                def lowvram_patch_counter(self):
                    return 0

            _PATCHER = NativeResidency()
        memory.load_models_gpu([_PATCHER], memory_required=3 * 1024**3, force_full_load=True)
        return _PATCHER.engine


def prepare_asr():
    release()
    MODEL_MANAGER.unload()
    try:
        import comfy.model_management as memory
        memory.free_memory(4 * 1024**3, torch.device("cuda:0"))
    except ImportError:
        pass


@contextmanager
def asr_cancellation(asr):
    cancel = threading.Event()
    stop = threading.Event()
    def watch():
        try:
            import comfy.model_management as memory
        except ImportError:
            return
        while not stop.wait(.05):
            if memory.processing_interrupted():
                cancel.set()
                asr.cancel()
                return
    thread = threading.Thread(target=watch, name="ming-comfy-cancel", daemon=True)
    thread.start()
    try:
        yield cancel
    finally:
        stop.set()
        thread.join(timeout=1)
