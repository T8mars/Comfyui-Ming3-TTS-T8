"""Optional C-ABI CUDA kernels, compatible with multiple host Torch versions."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

import torch

_LIB = None
_ERROR = None
_MODE = ContextVar("ming_kernel_mode", default=None)


def available():
    global _LIB, _ERROR
    if _LIB is not None:
        return True
    if _ERROR is not None or os.name != "nt" or not torch.cuda.is_available():
        return False
    folder = Path(__file__).resolve().parents[1] / "components/cuda"
    try:
        binary = folder / "ming_cuda.dll"
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if hashlib.sha256(binary.read_bytes()).hexdigest() != manifest["sha256"]:
            raise RuntimeError("Native CUDA component hash mismatch")
        library = ctypes.CDLL(str(binary))
        library.ming_kda.argtypes = [ctypes.c_void_p]*10 + [ctypes.c_int]*7 + [ctypes.c_float]*2 + [ctypes.c_int]*3 + [ctypes.c_size_t]
        library.ming_kda.restype = ctypes.c_int
        library.ming_expert.argtypes = [ctypes.c_void_p]*5 + [ctypes.c_int]*5 + [ctypes.c_size_t]
        library.ming_expert.restype = ctypes.c_int
        library.ming_cuda_error.argtypes = [ctypes.c_int]
        library.ming_cuda_error.restype = ctypes.c_char_p
        library.ming_kernel_version.restype = ctypes.c_int
        if library.ming_kernel_version() != 1:
            raise RuntimeError("Unsupported native CUDA component version")
        _LIB = library
        return True
    except Exception as error:
        _ERROR = str(error)
        return False


def status():
    from .config import configuration
    return {"available": available(), "error": _ERROR, "version": 1,
            "selected": os.environ.get("MING_T8_KERNELS", configuration().get("native_kernels", "portable"))}


def enabled():
    selected = os.environ.get("MING_T8_KERNELS") or _MODE.get()
    if selected is None:
        from .config import configuration
        selected = configuration().get("native_kernels", "portable")
    return selected in ("auto", "native") and available()


@contextmanager
def execution_mode(mode):
    token = _MODE.set(mode)
    try:
        yield
    finally:
        _MODE.reset(token)


def _check(code):
    if code:
        raise RuntimeError("Ming CUDA: " + _LIB.ming_cuda_error(code).decode("utf-8", errors="replace"))


def kda(q, k, v, g, beta, A_log=None, dt_bias=None, initial_state=None,
        output_final_state=True, use_qk_l2norm_in_kernel=True, use_gate_in_kernel=True,
        lower_bound=None, scale=None, **kwargs):
    if q.device.type != "cuda" or q.dtype not in (torch.bfloat16, torch.float32) or q.shape[-1] != 128:
        return None
    if k.dtype != q.dtype or v.dtype != q.dtype or g.dtype not in (torch.bfloat16, torch.float32):
        return None
    if not available():
        return None
    q, k, v, g = [item.contiguous() for item in (q, k, v, g)]
    beta = beta.float().contiguous()
    A_log = A_log.float().contiguous() if A_log is not None else None
    dt_bias = dt_bias.float().contiguous() if dt_bias is not None else None
    initial_state = initial_state.float().contiguous() if initial_state is not None else None
    B,T,H,K = q.shape
    V = v.shape[-1]
    if V > 256 or (use_gate_in_kernel and A_log is None):
        return None
    output = torch.empty_like(v)
    final = torch.empty((B,H,K,V), dtype=torch.float32, device=q.device)
    tensors = (q,k,v,g,beta,A_log,dt_bias,initial_state,output,final)
    pointers = [item.data_ptr() if item is not None else None for item in tensors]
    with torch.cuda.device(q.device):
        _check(_LIB.ming_kda(*pointers, B,T,H,K,V, int(q.dtype==torch.bfloat16), int(g.dtype==torch.bfloat16),
                             K**-.5 if scale is None else float(scale), lower_bound or 0.,
                             int(use_qk_l2norm_in_kernel), int(use_gate_in_kernel), int(lower_bound is not None),
                             torch.cuda.current_stream(q.device).cuda_stream))
    return output, final if output_final_state else None


def expert(value, indices, weight, scale, repeats=1):
    if value.device.type != "cuda" or value.dtype != torch.bfloat16 or scale.dtype not in (torch.bfloat16, torch.float32):
        return None
    if not available():
        return None
    value = value.contiguous()
    indices = indices.reshape(-1).to(torch.int64).contiguous()
    scale = scale.contiguous()
    pairs, N, K = indices.numel(), weight.shape[1], weight.shape[2]
    output = torch.empty((pairs,N), device=value.device, dtype=value.dtype)
    with torch.cuda.device(value.device):
        _check(_LIB.ming_expert(value.data_ptr(),indices.data_ptr(),weight.data_ptr(),scale.data_ptr(),output.data_ptr(),
                                pairs,repeats,N,K,int(scale.dtype==torch.bfloat16),torch.cuda.current_stream(value.device).cuda_stream))
    return output
