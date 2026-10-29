"""Load original HF shards and the published Comfy INT8 file without ComfyUI."""
from __future__ import annotations

import json
from pathlib import Path
import types

import torch
from torch import nn
from safetensors import safe_open

from .quantization import dequantize, PackedExperts, PackedMoE


def _stable_state_tensor(name, tensor):
    protected = name.endswith((".mlp.gate.expert_bias", ".attention.A_log", ".attention.dt_bias")) or name in (
        "flowloss.cfm.model.rotary_embed.inv_freq", "linear_proj_audio.rotary_embed.inv_freq")
    # Preserve checkpoint values while restoring the released FP32 runtime state.
    # The converted single-file export stores the two rotary tables in BF16.
    return tensor.float() if protected else tensor


def _target_name(source):
    if source.startswith("cond_stage_model."):
        return source.removeprefix("cond_stage_model.")
    if source.startswith("first_stage_model."):
        return "audio." + source.removeprefix("first_stage_model.")
    if source.startswith("model.diffusion_model."):
        return "flowloss.cfm.model." + source.removeprefix("model.diffusion_model.")
    return None


def _assign(module, name, tensor):
    prefix, leaf = name.rsplit(".", 1)
    parent = module.get_submodule(prefix)
    old = getattr(parent, leaf)
    if old.shape != tensor.shape:
        raise ValueError(f"Weight shape mismatch {name}: model={old.shape}, file={tensor.shape}")
    if leaf in parent._parameters:
        setattr(parent, leaf, nn.Parameter(tensor, requires_grad=False))
    elif leaf in parent._buffers:
        parent._buffers[leaf] = tensor
    else:
        raise ValueError(f"Unregistered state field {name}")


def _quant_info(source, prefix):
    key = prefix + ".comfy_quant"
    if key not in source.keys():
        return None
    result = json.loads(bytes(source.get_tensor(key).tolist()).decode("utf-8"))
    if result.get("format") != "int8_tensorwise":
        raise ValueError(f"Unsupported quantization format at {prefix}: {result}")
    return result


def skip_unused_text_logits(model):
    """TTS consumes backbone hidden states, so avoid projecting 157k text logits."""
    def forward(backbone, *args, **kwargs):
        kwargs.pop("logits_to_keep", None)
        return backbone.model(*args, **kwargs)
    model.model.forward = types.MethodType(forward, model.model)


def load_comfy_weights(model, checkpoint, device, *, progress=None):
    checkpoint = Path(checkpoint)
    loaded, skipped = set(), []
    with safe_open(str(checkpoint), framework="pt", device="cpu") as source:
        names = set(source.keys())
        metadata = source.metadata() or {}
        if "ming_config" not in metadata:
            raise ValueError("This file has no Ming model metadata")
        packed_prefixes = sorted({name.rsplit(".experts.", 1)[0] for name in names
                                  if name.endswith(".experts.gate_up_proj.weight")})
        for number, prefix in enumerate(packed_prefixes, 1):
            target = _target_name(prefix)
            original = model.get_submodule(target)
            up_name = prefix + ".experts.gate_up_proj"
            down_name = prefix + ".experts.down_proj"
            up_info, down_info = _quant_info(source, up_name), _quant_info(source, down_name)
            if up_info is None or down_info is None:
                raise ValueError(f"Packed expert quantization descriptor is missing: {prefix}")
            if (up_info.get("convrot", False), up_info.get("convrot_groupsize", 256)) != (
                down_info.get("convrot", False), down_info.get("convrot_groupsize", 256)
            ):
                raise ValueError(f"Gate/down expert rotation layouts disagree: {prefix}")
            bank = PackedExperts(
                source.get_tensor(up_name + ".weight").to(device),
                source.get_tensor(up_name + ".weight_scale").to(device),
                source.get_tensor(down_name + ".weight").to(device),
                source.get_tensor(down_name + ".weight_scale").to(device),
                convrot=up_info.get("convrot", False), group_size=up_info.get("convrot_groupsize", 256),
            )
            parent_name, leaf = target.rsplit(".", 1)
            setattr(model.get_submodule(parent_name), leaf, PackedMoE(original.gate, original.shared_experts, bank))
            if progress:
                progress("loading", number / max(len(packed_prefixes), 1) * .6, f"加载量化专家 {number}/{len(packed_prefixes)}")
        expected = dict(model.named_parameters())
        expected.update(dict(model.named_buffers()))
        for number, name in enumerate(sorted(names)):
            if ".experts." in name or name.endswith((".comfy_quant", ".weight_scale")):
                continue
            target = _target_name(name)
            if target is None or target.startswith("speaker.") or target == "tokenizer_json":
                skipped.append(name)
                continue
            if target not in expected:
                raise ValueError(f"Checkpoint contains an unmapped tensor: {name} -> {target}")
            tensor = source.get_tensor(name)
            if tensor.dtype == torch.int8:
                if not name.endswith(".weight"):
                    raise ValueError(f"INT8 non-weight tensor is unsupported: {name}")
                prefix = name.removesuffix(".weight")
                info = _quant_info(source, prefix)
                if info is None:
                    raise ValueError(f"Quantization descriptor missing: {name}")
                tensor = dequantize(tensor.to(device), source.get_tensor(prefix + ".weight_scale").to(device),
                                    convrot=info.get("convrot", False), group_size=info.get("convrot_groupsize", 256))
            else:
                # Preserve FP32 routing/state tensors. The unused text output head stays on CPU.
                tensor = tensor.to("cpu" if target == "model.lm_head.weight" else device)
            _assign(model, target, _stable_state_tensor(target,tensor))
            loaded.add(target)
        # The published TTS-only file deliberately omits the unused text LM head.
        # Remove that module rather than inventing weights or tying it to embeddings.
        if "model.lm_head.weight" not in loaded:
            model.model.lm_head = None
        missing = [name for name, value in model.named_parameters() if value.is_meta]
        if missing:
            raise ValueError(f"Uninitialized model tensors: {missing[:25]} (total {len(missing)})")
        # Nonpersistent rotary buffers are reconstructed from the frozen config.
        for name, value in list(model.named_buffers()):
            if value.is_meta:
                raise ValueError(f"Uninitialized runtime buffer: {name}")
            if value.device != torch.device(device):
                _assign(model, name, value.to(device))
    skip_unused_text_logits(model)
    return {"format": "comfy-int8-convrot", "loaded_tensors": len(loaded),
            "packed_expert_layers": len(packed_prefixes), "auxiliary_tensors": len(skipped)}


def validate_native_dtypes(model):
    groups = {
        "expert_bias": [(name, value) for name, value in model.named_buffers()
                        if name.endswith(".mlp.gate.expert_bias")],
        "kda_state": [(name, value) for name, value in model.named_parameters()
                      if name.endswith((".attention.A_log", ".attention.dt_bias"))],
        "flow_rotary": [(name, value) for name, value in model.named_buffers()
                        if name in ("flowloss.cfm.model.rotary_embed.inv_freq", "linear_proj_audio.rotary_embed.inv_freq")],
    }
    expected_counts = {"expert_bias": 23, "kda_state": 36, "flow_rotary": 2}
    for kind, tensors in groups.items():
        if len(tensors) != expected_counts[kind]:
            raise ValueError(f"Invalid {kind} tensor count: {len(tensors)}/{expected_counts[kind]}")
        wrong = [(name, value.dtype) for name, value in tensors if value.dtype != torch.float32]
        if wrong:
            raise ValueError(f"FP32 numerical state changed dtype: {wrong}")
    return {name: len(value) for name, value in groups.items()}


def load_official_weights(model, directory, device, *, progress=None):
    root = Path(directory)
    index = json.loads((root / "model.safetensors.index.json").read_text(encoding="utf-8"))
    shards = sorted(set(index["weight_map"].values()))
    for number, shard in enumerate(shards, 1):
        with safe_open(str(root / shard), framework="pt", device="cpu") as source:
            for name in source.keys():
                _assign(model, name, _stable_state_tensor(name,source.get_tensor(name)).to("cpu" if name == "model.lm_head.weight" else device))
        if progress:
            progress("loading", number / len(shards), f"加载原始权重 {number}/{len(shards)}")
    missing = [name for name, value in model.named_parameters() if value.is_meta]
    if missing:
        raise ValueError(f"Original model shards leave uninitialized tensors: {missing[:20]}")
    for name, value in list(model.named_buffers()):
        if value.is_meta:
            raise ValueError(f"Uninitialized runtime buffer: {name}")
        if value.device != torch.device(device):
            _assign(model, name, value.to(device))
    skip_unused_text_logits(model)
    return {"format": "official-bf16", "shards": len(shards)}
