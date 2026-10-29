"""Ming's interleaved rotary embedding subset, implemented directly in Torch.

The interface follows the MIT-licensed x-transformers rotary utilities; keeping
this small inference-only subset avoids installing that full framework in Comfy.
"""
import torch
from torch import nn


class RotaryEmbedding(nn.Module):
    def __init__(self, dim, base=10000):
        super().__init__()
        self.register_buffer("inv_freq", 1.0 / (base ** (torch.arange(0, dim, 2).float() / dim)))

    def forward_from_seq_len(self, seq_len):
        return self.forward(torch.arange(seq_len, device=self.inv_freq.device))

    def forward(self, positions, offset=0):
        with torch.autocast(device_type=self.inv_freq.device.type, enabled=False):
            if positions.ndim == 1:
                positions = positions.unsqueeze(0)
            angles = positions.to(self.inv_freq)[:, :, None] * self.inv_freq[None, None, :]
            return angles.repeat_interleave(2, dim=-1), 1.0


def apply_rotary_pos_emb(value, frequencies, scale=1):
    width, length, dtype = frequencies.shape[-1], value.shape[-2], value.dtype
    frequencies = frequencies[:, -length:]
    if isinstance(scale, torch.Tensor):
        scale = scale[:, -length:]
    if value.ndim == 4 and frequencies.ndim == 3:
        frequencies = frequencies.unsqueeze(1)
    head, tail = value[..., :width], value[..., width:]
    pairs = head.reshape(*head.shape[:-1], -1, 2)
    rotated = torch.stack((-pairs[..., 1], pairs[..., 0]), dim=-1).flatten(-2)
    output = head * frequencies.cos() * scale + rotated * frequencies.sin() * scale
    return torch.cat((output, tail), dim=-1).to(dtype)
