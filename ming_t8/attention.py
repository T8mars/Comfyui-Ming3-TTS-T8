"""Explicit FlashAttention selection with mask-safe SDPA fallback."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import importlib.metadata

import torch
import torch.nn.functional as F

_MODE = ContextVar("ming_attention_mode", default="sdpa")
_FLASH = None
_ERROR = None
_ORIGINAL = None


def flash_available():
    global _FLASH, _ERROR
    if _FLASH is not None:
        return True
    if _ERROR is not None:
        return False
    try:
        from flash_attn import flash_attn_func
        _FLASH = flash_attn_func
        return True
    except (ImportError, OSError, RuntimeError) as error:
        _ERROR = str(error)
        return False


def select_backend(requested):
    # The measured small MLA/Flow shapes are faster with this Torch build's
    # automatic SDPA dispatcher. Explicit Flash remains available for comparison.
    if requested in ("sdpa", "auto"):
        return "sdpa"
    if requested not in ("auto", "flash_attention_2"):
        raise ValueError("不支持的注意力后端")
    if torch.cuda.is_available() and flash_available():
        return "flash_attention_2"
    if requested == "flash_attention_2":
        raise RuntimeError(f"FlashAttention不可用，请使用匹配当前Python/Torch/CUDA的轮子或选择自动：{_ERROR}")
    return "sdpa"


@contextmanager
def execution_mode(mode):
    token = _MODE.set(mode)
    try:
        yield
    finally:
        _MODE.reset(token)


def mla_forward(module, query, key, value, attention_mask, scaling, dropout=0., **kwargs):
    # A nonempty additive mask can represent padding or a cached chunk's offset.
    # Keep its exact meaning instead of guessing a FlashAttention causal mode.
    if (_MODE.get() != "flash_attention_2" or attention_mask is not None or module.training
            or query.device.type != "cuda" or query.dtype not in (torch.float16, torch.bfloat16)
            or not flash_available() or (query.shape[-2] not in (1, key.shape[-2]))):
        return _ORIGINAL(module,query,key,value,attention_mask,scaling,dropout,**kwargs)
    from ._vendor.ming_tiny.modeling_bailing_moe_v3 import repeat_kv2
    key = repeat_kv2(key,module.num_key_value_groups)
    value = repeat_kv2(value,module.num_key_value_groups)
    width = value.shape[-1]
    padded = max(query.shape[-1], width)
    query = F.pad(query,(0,padded-query.shape[-1]))
    key = F.pad(key,(0,padded-key.shape[-1]))
    value = F.pad(value,(0,padded-width))
    output = _FLASH(query.transpose(1,2),key.transpose(1,2),value.transpose(1,2),
                    softmax_scale=scaling,dropout_p=0.,causal=query.shape[-2]>1)
    return output[...,:width].contiguous(), None


def install():
    global _ORIGINAL
    from ._vendor.ming_tiny import modeling_bailing_moe_v3 as backbone
    if _ORIGINAL is None:
        _ORIGINAL = backbone.sdpa_attention_forward
        backbone.sdpa_attention_forward = mla_forward


def status():
    found = flash_available()
    return {"available":found,"version":importlib.metadata.version("flash-attn") if found else None,"error":_ERROR}
