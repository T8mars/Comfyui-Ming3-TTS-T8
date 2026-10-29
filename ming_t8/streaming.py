"""Incremental AudioVAE reconstruction with lookahead and ISTFT state."""
from __future__ import annotations

import torch


class AudioStreamer:
    def __init__(self, audio_vae, callback, *, sample_rate=44100, chunk_frames=8):
        self.audio_vae = audio_vae
        self.callback = callback
        self.sample_rate = sample_rate
        self.chunk_frames = chunk_frames
        self.pending = []
        self.frames = 0
        self.state = (None, None, None)
        self.cache = None
        self.chunks = []

    def _decode(self, latent, final):
        waveform, self.state, self.cache = self.audio_vae.decode(
            latent, past_key_values=self.cache, use_cache=True,
            stream_state=self.state, last_chunk=final,
        )
        if waveform.numel():
            value = waveform.detach().float().cpu()
            self.chunks.append(value)
            self.callback(value, self.sample_rate, final)

    def feed(self, latent):
        self.pending.append(latent)
        self.frames += latent.shape[1]
        # Keep one tail chunk so the final flush always has real latent input.
        if self.frames >= 2 * self.chunk_frames:
            combined = torch.cat(self.pending, dim=1)
            self._decode(combined[:, :self.chunk_frames], False)
            remaining = combined[:, self.chunk_frames:]
            self.pending = [remaining]
            self.frames = remaining.shape[1]

    def finish(self):
        if self.pending:
            self._decode(torch.cat(self.pending, dim=1), True)
        self.pending.clear()
        self.cache = None
        self.state = (None, None, None)
        if not self.chunks:
            raise RuntimeError("增量音频解码没有产生可播放的音频")
        result = torch.cat(self.chunks, dim=-1)
        self.chunks.clear()
        return result
