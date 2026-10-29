"""Independent INT8/ConvRot tensor decoding and selected-expert inference.

ConvRot's regular Hadamard layout is documented by Apache-2.0 comfy-kitchen.
This module does not import ComfyUI or comfy-kitchen.
"""
from __future__ import annotations

import math
import torch
from torch import nn
import torch.nn.functional as F

_ROTATIONS = {}


def regular_hadamard(size=256, *, device="cpu", dtype=torch.float32):
    key = (size, str(device), dtype)
    if key not in _ROTATIONS:
        power = math.log(size, 4) if size >= 4 else -1
        if power < 1 or not power.is_integer():
            raise ValueError("ConvRot group size must be a positive power of four")
        base = torch.tensor([[1, 1, 1, -1], [1, 1, -1, 1],
                             [1, -1, 1, 1], [-1, 1, 1, 1]], device=device, dtype=dtype)
        matrix = base
        while matrix.shape[0] < size:
            matrix = torch.kron(matrix, base)
        _ROTATIONS[key] = matrix / math.sqrt(size)
    return _ROTATIONS[key]


def rotate(value, group_size=256):
    if value.shape[-1] % group_size:
        raise ValueError(f"Cannot rotate width {value.shape[-1]} using groups of {group_size}")
    original_shape = value.shape
    matrix = regular_hadamard(group_size, device=value.device, dtype=value.dtype)
    return (value.reshape(-1, group_size) @ matrix).reshape(original_shape)


def dequantize(weight, scale, *, convrot=False, group_size=256, dtype=torch.bfloat16):
    restored = weight.float() * scale.float()
    if convrot:
        restored = rotate(restored, group_size)
    return restored.to(dtype)


class PackedExperts(nn.Module):
    """Keep all expert weights in INT8; materialize only routed rows."""
    def __init__(self, gate_up, gate_up_scale, down, down_scale, *, convrot=True, group_size=256):
        super().__init__()
        self.register_buffer("gate_up", gate_up)
        self.register_buffer("gate_up_scale", gate_up_scale)
        self.register_buffer("down", down)
        self.register_buffer("down_scale", down_scale)
        self.convrot, self.group_size = convrot, group_size

    def selected(self, value, indices):
        # Bound temporary memory for long prefill. Decode uses one row and eight experts.
        count, selected = indices.shape
        if count > 8:
            return torch.cat([self.selected(value[i:i+8], indices[i:i+8]) for i in range(0, count, 8)])
        from .cuda_kernels import enabled, expert
        if enabled() and value.dtype == torch.bfloat16 and value.device.type == "cuda":
            rotated = rotate(value.float(), self.group_size).to(value.dtype) if self.convrot else value
            projection = expert(rotated, indices, self.gate_up, self.gate_up_scale, repeats=selected)
            if projection is not None:
                gate, up = projection.chunk(2, dim=-1)
                intermediate = F.silu(gate) * up
                if self.convrot:
                    intermediate = rotate(intermediate.float(), self.group_size).to(value.dtype)
                output = expert(intermediate, indices, self.down, self.down_scale)
                if output is not None:
                    return output.reshape(count, selected, value.shape[-1])
        flat_indices = indices.reshape(-1)
        inputs = value[:, None, :].expand(-1, selected, -1).reshape(-1, 1, value.shape[-1])
        if self.convrot:
            inputs = rotate(inputs.float(), self.group_size).to(value.dtype)
        weight = (self.gate_up[flat_indices].float() * self.gate_up_scale[flat_indices].float()).to(value.dtype)
        gate, up = torch.bmm(inputs, weight.transpose(1, 2)).chunk(2, dim=-1)
        intermediate = F.silu(gate) * up
        if self.convrot:
            intermediate = rotate(intermediate.float(), self.group_size).to(value.dtype)
        weight = (self.down[flat_indices].float() * self.down_scale[flat_indices].float()).to(value.dtype)
        output = torch.bmm(intermediate, weight.transpose(1, 2))
        return output.reshape(count, selected, value.shape[-1])


class PackedMoE(nn.Module):
    def __init__(self, gate, shared_experts, experts):
        super().__init__()
        self.gate, self.shared_experts, self.experts = gate, shared_experts, experts

    def forward(self, hidden_states):
        shape = hidden_states.shape
        indices, weights, logits = self.gate(hidden_states)
        flat = hidden_states.reshape(-1, shape[-1])
        outputs = self.experts.selected(flat, indices)
        routed = (outputs.float() * weights.unsqueeze(-1)).sum(1).to(hidden_states.dtype).reshape(shape)
        return routed + self.shared_experts(hidden_states), (logits.reshape(*shape[:2], -1), indices.reshape(*shape[:2], -1))
