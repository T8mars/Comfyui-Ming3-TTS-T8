"""In-process Ming Tiny engine shared by desktop and custom nodes."""
from __future__ import annotations

import gc
import os
from pathlib import Path
import threading
import time

import torch

from .contracts import TaskRequest
from .config import configuration


class GenerationCancelled(RuntimeError):
    pass


class NativeEngine:
    def __init__(self, model_path=None, assets_path=None, device=None, *, progress=None, profile=None):
        from accelerate import init_empty_weights
        from transformers import PreTrainedTokenizerFast
        from ._vendor.ming_tiny.task_protocol import configure_release_environment
        from .kda import install_portable_kda
        configure_release_environment()
        install_portable_kda()
        from ._vendor.ming_tiny.configuration_lingv3_tts import LingV3TTSConfig
        from ._vendor.ming_tiny.modeling_lingv3_tts import LingV3TTSForConditionalGeneration
        from ._vendor.ming_tiny.inference import MingTinyEngine, prompt_conditioning_geometry
        from ._vendor.ming_tiny import inference as inference_module
        from .audio import load_prompt_waveform
        inference_module.load_prompt_waveform = load_prompt_waveform
        from ._vendor.ming_tiny.prompt_contract import (
            with_rml, protocol_version, prompt_format, tokenizer_contract,
            sampling_contract, decode_alignment, task_decode_alignments,
        )
        from ._vendor.ming_tiny.spkemb_extractor import SpkembExtractor
        from .weights import load_comfy_weights, load_official_weights, validate_native_dtypes
        settings = configuration()
        if profile:
            if set(profile)-{"native_kernels","attention_backend","cuda_graphs"}:
                raise ValueError("不支持的原生执行选项")
            settings.update(profile)
        self.model_path = Path(model_path or settings["model_path"]).resolve()
        self.assets_path = Path(assets_path or settings["assets_path"]).resolve()
        self.device = torch.device(device or settings["device"])
        self.execution_profile = {"kernels": os.environ.get("MING_T8_KERNELS", settings.get("native_kernels", "portable")),
                                  "attention": settings.get("attention_backend", "sdpa"),
                                  "cuda_graphs": bool(settings.get("cuda_graphs",False))}
        from .attention import select_backend, install as install_attention
        self.execution_profile["attention"] = select_backend(self.execution_profile["attention"]) if self.device.type == "cuda" else "sdpa"
        install_attention()
        if self.device.type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("未检测到可用的NVIDIA GPU，请检查驱动与PyTorch CUDA版本")
        if not self.model_path.exists():
            raise FileNotFoundError(f"模型尚未下载完成：{self.model_path}")
        self.cancel_event = threading.Event()
        self.progress = progress
        self.lock = threading.RLock()
        self.closed = False
        if progress:
            progress("verifying", 0, "校验模型与辅助文件的内容版本")
        from .provenance import model_identity
        self.identity = model_identity(self.model_path, self.assets_path)
        config = LingV3TTSConfig.from_pretrained(str(self.assets_path), local_files_only=True)
        config.llm_config._attn_implementation = "sdpa"
        # Qwen AudioVAE reads this private setting only during construction.
        if self.execution_profile["attention"] == "flash_attention_2":
            config.aggregator_config["attn_backend"] = "flash_attn"
            config.flow_config["attn_backend"] = "flash_attn"
        self.config = config
        # Keep the release's BPE regex. New Transformers' Mistral heuristic also
        # matches this Qwen-family tokenizer; applying that fix changes its IDs.
        self.tokenizer = PreTrainedTokenizerFast.from_pretrained(str(self.assets_path), local_files_only=True, fix_mistral_regex=False)
        if progress:
            progress("loading", 0, "创建原生模型结构")
        started = time.perf_counter()
        previous_audio_backend=os.environ.get("MING_TINY_AUDIO_VAE_ATTN")
        try:
            os.environ["MING_TINY_AUDIO_VAE_ATTN"] = self.execution_profile["attention"]
            with init_empty_weights(include_buffers=False):
                model = LingV3TTSForConditionalGeneration(config)
        finally:
            if previous_audio_backend is None:os.environ.pop("MING_TINY_AUDIO_VAE_ATTN",None)
            else:os.environ["MING_TINY_AUDIO_VAE_ATTN"]=previous_audio_backend
        self.model = model
        if self.model_path.is_file():
            self.load_info = load_comfy_weights(model, self.model_path, self.device, progress=progress)
        else:
            self.load_info = load_official_weights(model, self.model_path, self.device, progress=progress)
        model.eval()
        model.validate_tts_tokenizer(self.tokenizer)
        self.load_info["dtype_validation"] = validate_native_dtypes(model)
        self.load_info["seconds"] = time.perf_counter() - started
        self.model = model
        self.graphs = []
        if self.execution_profile["cuda_graphs"] and self.device.type == "cuda":
            from .graphs import install as install_graphs
            self.graphs = install_graphs(model)
        # Use released conditioning/sampling algorithms with our independently loaded model.
        engine = MingTinyEngine.__new__(MingTinyEngine)
        engine.config, engine.model, engine.tokenizer = config, model, self.tokenizer
        engine.device, engine.dtype = self.device, torch.bfloat16
        engine.model_dir, engine.tokenizer_dir = str(self.assets_path), str(self.assets_path)
        engine.with_rml = with_rml(config.tts_config)
        engine.prompt_geometry = prompt_conditioning_geometry(config)
        engine.protocol_version = protocol_version(config.tts_config)
        engine.prompt_format = prompt_format(config.tts_config)
        engine.tokenizer_contract = tokenizer_contract(config.tts_config)
        engine.sampling_contract = sampling_contract(config.tts_config)
        engine.decode_alignment = decode_alignment(config.tts_config)
        engine.task_decode_alignment = task_decode_alignments(config.tts_config)
        engine.task_contract = config.tts_config.get("task_contract")
        engine.enable_tts_target_language = config.tts_config.get("enable_tts_target_language", False)
        engine.infer_tts_language_from_text = config.tts_config.get("infer_tts_language_from_text", False)
        engine.moe_backend, engine.runtime_state_dtype = "loop", "stable_fp32"
        engine.campplus_path = str(self.assets_path / "campplus.onnx")
        from .audio import CachedSpeakerExtractor
        engine.speaker_extractor = CachedSpeakerExtractor(SpkembExtractor(engine.campplus_path))
        from ._vendor.ming_tiny.task_protocol import validate_release_engine
        validate_release_engine(engine)
        self.native = engine
        from ._vendor.ming_tiny.api import MingTinyTTS
        self.api = MingTinyTTS(engine)
        self.model._t8_control = {"cancel": self.cancel_event, "progress": progress}
        if progress:
            progress("ready", 1, "模型已就绪")

    @property
    def sample_rate(self):
        return int(self.config.tts_config["sample_rate"])

    def generate(self, request: TaskRequest, *, output_path=None, progress=None, audio_callback=None):
        request.validate()
        with self.lock:
            if self.closed:
                raise RuntimeError("模型已经释放，请重新加载")
            self.cancel_event.clear()
            def check_cancel():
                if self.cancel_event.is_set():
                    raise GenerationCancelled("任务已取消")
            streamer = None
            if audio_callback is not None:
                from .streaming import AudioStreamer
                streamer = AudioStreamer(self.model.audio, audio_callback, sample_rate=self.sample_rate)
            self.model._t8_control = {"cancel": self.cancel_event, "progress": progress or self.progress,
                                      "check_cancel": check_cancel, "streamer": streamer}
            started = time.perf_counter()
            if self.device.type == "cuda":
                torch.cuda.reset_peak_memory_stats(self.device)
            try:
                from .cuda_kernels import execution_mode
                from .attention import execution_mode as attention_mode
                with execution_mode(self.execution_profile["kernels"]), attention_mode(self.execution_profile["attention"]):
                    output = self.api.generate(**request.api_arguments(), output_path=None)
                    if output_path:
                        from .audio import save_waveform
                        save_waveform(output_path,output.waveform,self.sample_rate)
            finally:
                self.model._t8_control = {}
            if self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
            duration = output.waveform.shape[-1] / self.sample_rate
            elapsed = time.perf_counter() - started
            metrics = {"seconds": elapsed, "audio_seconds": duration, "rtf": elapsed / max(duration, .001),
                       "stopped": output.stopped, "truncated": not output.stopped,
                       "prompt_tokens": output.prompt_token_count, "latent_steps": output.latents.shape[1],
                       "format": self.load_info["format"], "device": str(self.device),
                       "seed": request.seed if request.seed is not None else (1235 if request.task == "podcast" else 1234),
                       "model_identity": self.identity}
            metrics["execution_profile"] = self.execution_profile
            metrics["cuda_graphs"] = [wrapper.status() for wrapper in self.graphs]
            if self.device.type == "cuda":
                metrics.update(gpu_allocated=torch.cuda.max_memory_allocated(self.device),
                               gpu_reserved=torch.cuda.max_memory_reserved(self.device))
            return output, metrics

    def cancel(self):
        self.cancel_event.set()

    def clear_acceleration_caches(self):
        for graph in getattr(self,"graphs",[]):
            graph.clear()

    def close(self):
        self.cancel_event.set()
        with self.lock:
            self.clear_acceleration_caches()
            if getattr(self,"graphs",None):
                from .graphs import uninstall
                uninstall(self.graphs)
            self.closed = True
            self.api = self.native = self.model = None
            from .audio import clear_reference_cache
            clear_reference_cache()
            gc.collect()
            if self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
                torch.cuda.empty_cache()


class ModelManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.engine = None
        self.key = None

    def request_key(self, model_path=None, assets_path=None, device=None):
        import json
        settings=configuration()
        model_path=Path(model_path or settings["model_path"]).resolve()
        assets_path=Path(assets_path or settings["assets_path"]).resolve()
        paths=[model_path] if not model_path.is_dir() else sorted(model_path.glob("*.safetensors"))+[model_path/"model.safetensors.index.json"]
        paths += [assets_path/name for name in ("config.json","tokenizer.json","campplus.onnx")]
        signatures=tuple((str(path),path.stat().st_size,path.stat().st_mtime_ns) if path.is_file() else (str(path),None,None) for path in paths)
        profile=tuple((name,settings.get(name)) for name in ("native_kernels","attention_backend","cuda_graphs"))
        return (str(model_path),str(assets_path),device or settings["device"],signatures,profile)

    def get(self, model_path=None, assets_path=None, device=None, *, progress=None):
        settings = configuration()
        model_path = str(Path(model_path or settings["model_path"]).resolve())
        assets_path = str(Path(assets_path or settings["assets_path"]).resolve())
        device = device or settings["device"]
        key = self.request_key(model_path, assets_path, device)
        with self.lock:
            if self.engine is None or self.engine.closed or self.key != key:
                self.unload()
                pending=NativeEngine.__new__(NativeEngine)
                try:
                    pending.__init__(model_path,assets_path,device,progress=progress)
                except Exception:
                    if hasattr(pending,"model"):
                        pending.close()
                    gc.collect()
                    if torch.cuda.is_available():torch.cuda.empty_cache()
                    raise
                self.engine = pending
                self.key = key
            return self.engine

    def unload(self):
        with self.lock:
            if self.engine is not None:
                self.engine.close()
            self.engine, self.key = None, None


MODEL_MANAGER = ModelManager()
