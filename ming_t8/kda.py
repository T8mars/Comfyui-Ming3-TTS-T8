"""Portable inference kernels for Ming's key-channel-gated delta attention.

The recurrence follows the MIT-licensed FLA mathematical reference:
https://github.com/fla-org/flash-linear-attention/blob/main/fla/ops/kda/naive.py
No external service, Comfy runtime, or Triton dependency is needed by this path.
"""
from __future__ import annotations

import torch
from torch import nn
import torch.nn.functional as F


class ShortConvolution(nn.Module):
    def __init__(self, hidden_size, kernel_size, activation="silu", bias=False, **kwargs):
        super().__init__()
        self.weight = nn.Parameter(torch.empty(hidden_size, 1, kernel_size))
        self.bias = nn.Parameter(torch.zeros(hidden_size)) if bias else None
        self.kernel_size = kernel_size
        self.activation = activation

    def forward(self, x, cache=None, output_final_state=False, cu_seqlens=None, **kwargs):
        if cu_seqlens is not None:
            raise ValueError("Packed variable-length KDA batches are not enabled in this inference kernel")
        channels_first = x.transpose(1, 2)
        if cache is None:
            history = channels_first.new_zeros(x.shape[0], x.shape[-1], self.kernel_size - 1)
        else:
            history = cache[..., -(self.kernel_size - 1):]
        combined = torch.cat((history, channels_first), dim=-1)
        output = F.conv1d(combined, self.weight, self.bias, groups=x.shape[-1]).transpose(1, 2)
        if self.activation == "silu":
            output = F.silu(output)
        elif self.activation is not None:
            raise ValueError(f"Unsupported convolution activation: {self.activation}")
        final = combined[..., -self.kernel_size:].contiguous() if output_final_state else None
        return output, final


class RMSNormGated(nn.Module):
    def __init__(self, hidden_size, eps=1e-6, activation="sigmoid", **kwargs):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(hidden_size))
        self.eps = eps
        self.activation = activation

    def forward(self, value, gate):
        normalized = value.float() * torch.rsqrt(value.float().square().mean(-1, keepdim=True) + self.eps)
        normalized = normalized * self.weight.float()
        if self.activation == "sigmoid":
            normalized = normalized * gate.float().sigmoid()
        else:
            raise ValueError(f"Unsupported gated norm activation: {self.activation}")
        return normalized.to(value.dtype)


def recurrent_kda(q, k, v, g, beta, A_log=None, dt_bias=None, initial_state=None,
                  output_final_state=True, use_qk_l2norm_in_kernel=True,
                  use_gate_in_kernel=True, safe_gate=False, lower_bound=None,
                  cu_seqlens=None, scale=None, **kwargs):
    if cu_seqlens is not None:
        raise ValueError("Packed variable-length KDA is not supported in the portable path")
    from .cuda_kernels import enabled, kda
    if enabled():
        result = kda(q, k, v, g, beta, A_log, dt_bias, initial_state, output_final_state,
                     use_qk_l2norm_in_kernel, use_gate_in_kernel, lower_bound, scale)
        if result is not None:
            return result
    output_dtype = v.dtype
    q, k, v, g, beta = (item.float() for item in (q, k, v, g, beta))
    if use_qk_l2norm_in_kernel:
        q = q * torch.rsqrt(q.square().sum(-1, keepdim=True) + 1e-6)
        k = k * torch.rsqrt(k.square().sum(-1, keepdim=True) + 1e-6)
    if use_gate_in_kernel:
        if dt_bias is not None:
            g = g + dt_bias.float().reshape(g.shape[-2:])
        if lower_bound is not None:
            g = float(lower_bound) * (g * A_log.float().exp().view(-1, 1)).sigmoid()
        else:
            g = -A_log.float().exp().view(-1, 1) * F.softplus(g)
    q = q * (q.shape[-1] ** -.5 if scale is None else scale)
    state = (q.new_zeros(q.shape[0], q.shape[2], q.shape[3], v.shape[3])
             if initial_state is None else initial_state.float())
    outputs = []
    for index in range(q.shape[1]):
        query, key, value = q[:, index], k[:, index], v[:, index]
        state = state * g[:, index].exp().unsqueeze(-1)
        residual = value - (state * key.unsqueeze(-1)).sum(-2)
        state = state + (key * beta[:, index].unsqueeze(-1)).unsqueeze(-1) * residual.unsqueeze(-2)
        outputs.append((state * query.unsqueeze(-1)).sum(-2))
    return torch.stack(outputs, dim=1).to(output_dtype), state if output_final_state else None


def install_portable_kda():
    from ._vendor.ming_tiny import modeling_bailing_moe_v3 as backbone
    backbone.ShortConvolution = ShortConvolution
    backbone.FusedRMSNormGated = RMSNormGated
    backbone.chunk_kda = recurrent_kda
    backbone.fused_recurrent_kda = recurrent_kda
    backbone._FLA_AVAILABLE = True
