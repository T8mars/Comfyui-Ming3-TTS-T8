"""Native custom nodes. Only generic Comfy AUDIO/path/progress APIs are used."""
from __future__ import annotations

import json
import math
from pathlib import Path
import uuid

if __package__:
    from .ming_t8.contracts import TaskRequest, TASK_LABELS
    from .ming_t8.config import configuration, data_directory
else:
    from ming_t8.contracts import TaskRequest, TASK_LABELS
    from ming_t8.config import configuration, data_directory


def core_modules():
    if __package__:
        from .ming_t8.engine import MODEL_MANAGER
        from .ming_t8.asr import ASR
    else:
        from ming_t8.engine import MODEL_MANAGER
        from ming_t8.asr import ASR
    return MODEL_MANAGER, ASR


def residency():
    if __package__:
        from .ming_t8 import comfy_residency
    else:
        from ming_t8 import comfy_residency
    return comfy_residency


class MingT8ModelLoader:
    @classmethod
    def IS_CHANGED(cls, model_path="", assets_path="", device="cuda:0"):
        manager,_=core_modules()
        return manager.request_key(model_path or None,assets_path or None,device)
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model_path": ("STRING", {"default": "", "tooltip": "留空使用本地配置中的模型"}),
                             "assets_path": ("STRING", {"default": "", "tooltip": "包含config/tokenizer/campplus的目录"}),
                             "device": (["cuda:0", "cpu"],)}}
    RETURN_TYPES = ("MING_T8_MODEL",)
    FUNCTION = "load"
    CATEGORY = "T8/Ming 3.0"

    def load(self, model_path="", assets_path="", device="cuda:0"):
        settings = configuration()
        handle = {"model_path": model_path.strip() or settings["model_path"],
                  "assets_path": assets_path.strip() or settings["assets_path"], "device": device}
        if not Path(handle["model_path"]).exists():
            raise ValueError("模型未准备好，请在工作台中下载，或填写正确的本地模型路径")
        # Lazy handle: reference ASR can run first without loading TTS twice.
        return (handle,)


class MingT8Reference:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audio": ("AUDIO",), "transcript": ("STRING", {"default": "", "multiline": True}),
                             "auto_transcribe": ("BOOLEAN", {"default": False}),
                             "language": (["Auto", "Chinese", "English", "Cantonese", "Japanese", "Korean", "German", "French", "Spanish"],)},
                "optional":{"start_seconds": ("FLOAT", {"default":0.0,"min":0.0,"step":0.1,"tooltip":"参考录音开始时间，单位秒"}),
                             "end_seconds": ("FLOAT", {"default":0.0,"min":0.0,"step":0.1,"tooltip":"0使用原音频结尾；转录应对应裁切后的录音"})}}
    RETURN_TYPES = ("MING_T8_REFERENCE", "STRING")
    RETURN_NAMES = ("reference", "transcript")
    FUNCTION = "prepare"
    CATEGORY = "T8/Ming 3.0"

    def prepare(self, audio, transcript="", auto_transcribe=False, language="Auto", start_seconds=0.0, end_seconds=0.0):
        import hashlib
        import soundfile as sf
        waveform = audio["waveform"].detach().cpu().float()
        if waveform.ndim != 3 or waveform.shape[0] != 1:
            raise ValueError("参考录音必须是单段AUDIO，batch=1")
        rate = int(audio["sample_rate"])
        if rate <= 0 or not waveform.shape[-1]:
            raise ValueError("参考音频采样率或长度无效")
        duration = waveform.shape[-1] / rate
        if not all(isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) for value in (start_seconds,end_seconds)):
            raise ValueError("裁切时间必须是有限数字")
        end = duration if end_seconds == 0 else end_seconds
        if not 0 <= start_seconds < end <= duration + 1/rate:
            raise ValueError("裁切范围无效：开始时间应早于结束时间，并位于录音长度之内")
        waveform = waveform[...,round(start_seconds*rate):round(end*rate)]
        import torch
        if not torch.isfinite(waveform).all() or not torch.any(waveform):
            raise ValueError("参考音频为空、全静音或包含无效数值")
        value = waveform[0].numpy().T
        signature = hashlib.sha256(value.tobytes() + str(rate).encode()).hexdigest()
        path = data_directory("references") / (signature + ".wav")
        if not path.is_file():
            sf.write(str(path), value, rate, subtype="FLOAT")
        machine_text = None
        if auto_transcribe:
            manager, asr = core_modules()
            residency().prepare_asr()
            with residency().asr_cancellation(asr) as cancelled:
                result = asr.transcribe(path, language=language, cancel_event=cancelled)
            if result.get("truncated"):
                raise ValueError("参考录音识别被截断，请缩短片段或手动填写转录")
            machine_text = result["text"]
            if not transcript.strip():
                transcript = machine_text
        reference = {"version": 1, "path": str(path), "sha256": signature, "text": transcript.strip(),
                     "machine_text": machine_text, "sample_rate": rate,
                     "crop": {"start":float(start_seconds),"end":float(end)}}
        return reference, transcript


class MingT8SpeakerBank:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"reference": ("MING_T8_REFERENCE",)},
                "optional": {"previous": ("MING_T8_SPEAKERS",)}}
    RETURN_TYPES = ("MING_T8_SPEAKERS",)
    FUNCTION = "append"
    CATEGORY = "T8/Ming 3.0"

    def append(self, reference, previous=None):
        return ([*(previous or []), reference],)


class MingT8Task:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "task": (list(TASK_LABELS), {"default": "ip"}),
            "text": ("STRING", {"multiline": True, "default": "你好，欢迎使用明语音工作台。"}),
            "language": (["Chinese", "English", "German", "Spanish", "French", "Korean", "Japanese"],),
            "ip": ("STRING", {"default": "灵小柔"}),
            "style": ("STRING", {"default": "年轻清晰、温暖自然的女声", "multiline": True}),
            "instruction": ("STRING", {"default": "用温暖自然的叙事语气讲述", "multiline": True}),
            "emotion": (["中性", "高兴", "悲伤", "愤怒", "惊讶", "恐惧", "厌恶"],),
            "dialect": (["川渝话", "广粤话"],),
            "speed": (["慢速", "中速", "快速"], {"default": "中速"}),
            "pitch": (["低", "中", "高"], {"default": "中"}),
            "volume": (["低", "中", "高"], {"default": "中"}),
        }, "optional": {"reference": ("MING_T8_REFERENCE",), "speakers": ("MING_T8_SPEAKERS",)}}
    RETURN_TYPES = ("MING_T8_REQUEST",)
    FUNCTION = "build"
    CATEGORY = "T8/Ming 3.0"

    def build(self, task, text, language="Chinese", ip="灵小柔", style="", instruction="",
              emotion="中性", dialect="川渝话", speed="中速", pitch="中", volume="中",
              reference=None, speakers=None):
        value = {"task": task, "text": text}
        if task in ("seed", "multilingual", "paralinguistic"):
            if reference is None:
                raise ValueError("此任务需要连接参考录音与对应转录")
            value.update(prompt_wav=reference["path"], prompt_text=reference["text"], target_language=language)
        elif task == "podcast":
            bank = speakers or []
            value.update(prompt_wav=[item["path"] for item in bank], prompt_text=[item["text"] for item in bank])
        elif task in ("basic", "emotion", "dialect"):
            if reference is None:
                raise ValueError("此任务需要连接参考音色录音")
            value["prompt_wav"] = reference["path"]
            if task == "basic":
                value.update(speed=speed, pitch=pitch, volume=volume)
            else:
                value[task] = emotion if task == "emotion" else dialect
        elif task == "freeform":
            value["instruction"] = instruction
            if reference is not None:
                value["prompt_wav"] = reference["path"]
        elif task == "voice_design":
            value["style"] = style
        elif task == "ip":
            value["ip"] = ip
        return (TaskRequest.from_dict(value).to_dict(),)


class MingT8Generate:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MING_T8_MODEL",), "request": ("MING_T8_REQUEST",),
            "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff, "control_after_generate": False, "tooltip":"-1使用任务默认：普通1234，联合对话1235"}),
            "cfg": ("FLOAT", {"default": 2.0, "min": 0.0, "max": 100.0}),
            "flow_steps": ("INT", {"default": 10, "min": 1, "max": 128}),
            "temperature": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 10.0}),
            "sigma": ("FLOAT", {"default": .25, "min": 0.0, "max": 10.0}),
            "minimum": ("INT", {"default": 0, "min": 0, "max": 16384, "tooltip": "0使用官方默认；Podcast单位为generation frames"}),
            "maximum": ("INT", {"default": 0, "min": 0, "max": 16384, "tooltip": "0使用官方默认；Podcast单位为generation frames"}),
            "stop_threshold": ("FLOAT", {"default": .5, "min": 0.0, "max": 1.0}),
            "log_every_n_steps": ("INT", {"default": 0, "min": 0, "max": 100000, "tooltip":"诊断日志间隔；0关闭"})}}
    RETURN_TYPES = ("AUDIO", "LATENT", "STRING")
    RETURN_NAMES = ("audio", "latent", "report")
    FUNCTION = "generate"
    CATEGORY = "T8/Ming 3.0"

    def generate(self, model, request, seed=-1, cfg=2.0, flow_steps=10, temperature=0.0,
                 sigma=.25, minimum=0, maximum=0, stop_threshold=.5, log_every_n_steps=0):
        value = {**request, "seed": None if seed == -1 else seed, "cfg_scale": cfg, "flow_steps": flow_steps,
                 "temperature": temperature, "sigma": sigma, "stop_threshold": stop_threshold,
                 "log_every_n_steps": log_every_n_steps}
        if request["task"] == "podcast":
            if minimum or maximum:
                value.update(min_generation_frames=minimum, max_generation_frames=maximum)
        else:
            value.update(min_decode_steps=minimum or None, max_decode_steps=maximum or None)
        parsed = TaskRequest.from_dict(value)
        manager, asr = core_modules()
        asr.unload()
        engine = residency().get_engine(**model)
        try:
            import comfy.model_management
            from comfy.utils import ProgressBar
            bar = ProgressBar(1000)
            def progress(phase, fraction, message):
                comfy.model_management.throw_exception_if_processing_interrupted()
                bar.update_absolute(round(fraction * 1000), 1000)
        except ImportError:
            progress = None
        output, metrics = engine.generate(parsed, progress=progress)
        audio = {"waveform": output.waveform.detach().cpu(), "sample_rate": engine.sample_rate}
        latent = {"samples": output.latents.detach().cpu().transpose(1, 2), "type": "audio", "downscale_ratio_temporal": 3528}
        report = json.dumps({"request": parsed.to_dict(), "metrics": metrics,
                             "conditioning":{"speaker_slots":output.speaker_slot_count,"campplus_rows":output.campplus_speaker_rows,"prompt_latent_steps":output.prompt_latent_steps}}, ensure_ascii=False, indent=2)
        return audio, latent, report


class MingT8Decode:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MING_T8_MODEL",), "latent": ("LATENT",)}}
    RETURN_TYPES = ("AUDIO",)
    FUNCTION = "decode"
    CATEGORY = "T8/Ming 3.0"

    def decode(self, model, latent):
        import torch
        manager, _ = core_modules()
        engine = residency().get_engine(**model)
        with engine.lock, torch.inference_mode(), torch.autocast(device_type=engine.device.type, dtype=torch.bfloat16):
            waveform = engine.model.audio.infer_from_latent(latent["samples"].transpose(1, 2).to(engine.device))
        return ({"waveform": waveform.detach().cpu().float(), "sample_rate": engine.sample_rate},)


class MingT8Save:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audio": ("AUDIO",), "filename_prefix": ("STRING", {"default": "MingT8/voice"})},
                "optional": {"report": ("STRING", {"forceInput": True})}}
    RETURN_TYPES = ("STRING",)
    OUTPUT_NODE = True
    FUNCTION = "save"
    CATEGORY = "T8/Ming 3.0"

    def save(self, audio, filename_prefix="MingT8/voice", report=""):
        import soundfile as sf
        import folder_paths
        root = Path(folder_paths.get_output_directory()).resolve()
        prefix = (root / filename_prefix).resolve()
        if not prefix.is_relative_to(root):
            raise ValueError("输出路径必须位于ComfyUI output目录")
        prefix.parent.mkdir(parents=True, exist_ok=True)
        path = prefix.with_name(prefix.name + "_" + uuid.uuid4().hex[:10] + ".wav")
        waveform = audio["waveform"].detach().cpu().float()
        if waveform.shape[0] != 1:
            raise ValueError("请逐段保存音频，batch必须为1")
        sf.write(str(path), waveform[0].numpy().T, int(audio["sample_rate"]), subtype="PCM_24")
        if report:
            path.with_suffix(".json").write_text(report, encoding="utf-8")
        return {"ui": {"audio": [{"filename": path.name, "subfolder": str(path.parent.relative_to(root)), "type": "output"}]},
                "result": (str(path),)}


class MingT8Unload:
    @classmethod
    def INPUT_TYPES(cls):
        return {"optional": {"model": ("MING_T8_MODEL",), "after_audio": ("AUDIO",)}}
    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")
    RETURN_TYPES = ("STRING",)
    OUTPUT_NODE = True
    FUNCTION = "unload"
    CATEGORY = "T8/Ming 3.0"

    def unload(self, model=None, after_audio=None):
        manager, asr = core_modules()
        residency().release()
        manager.unload()
        asr.unload()
        return ("Ming与Confucius模型已释放",)


class MingT8OneClick:
    @classmethod
    def INPUT_TYPES(cls):
        value = MingT8Task.INPUT_TYPES()
        value["required"].update({"model_path": ("STRING", {"default": ""}),
            "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff, "control_after_generate":False}),
            "flow_steps": ("INT", {"default": 10, "min": 1, "max": 128}),
            "auto_transcribe": ("BOOLEAN", {"default": True}),
            "reference_text": ("STRING", {"default": "", "multiline": True})})
        value["optional"].update({"reference_start": ("FLOAT", {"default":0.0,"min":0.0,"step":0.1}),
                                  "reference_end": ("FLOAT", {"default":0.0,"min":0.0,"step":0.1,"tooltip":"0使用原音频结尾"})})
        value["optional"]["audio"] = ("AUDIO",)
        return value
    RETURN_TYPES = ("AUDIO", "LATENT", "STRING")
    RETURN_NAMES = ("audio", "latent", "report")
    FUNCTION = "generate"
    CATEGORY = "T8/Ming 3.0"

    def generate(self, model_path="", seed=-1, flow_steps=10, auto_transcribe=True, reference_text="", reference_start=0.0, reference_end=0.0, audio=None, **arguments):
        task=arguments.get("task")
        if audio is not None and task in ("seed","multilingual","paralinguistic","basic","emotion","dialect","freeform"):
            needs_transcript=task in ("seed","multilingual","paralinguistic")
            reference, _ = MingT8Reference().prepare(audio, reference_text, needs_transcript and auto_transcribe and not reference_text.strip(),start_seconds=reference_start,end_seconds=reference_end)
            arguments["reference"] = reference
        request, = MingT8Task().build(**arguments)
        model, = MingT8ModelLoader().load(model_path)
        return MingT8Generate().generate(model, request, seed=seed, flow_steps=flow_steps)


class MingT8Voice:
    @classmethod
    def INPUT_TYPES(cls):
        catalog = json.loads((Path(__file__).parent / "ming_t8/assets/voices.json").read_text(encoding="utf-8"))
        return {"required": {"voice": ([item["id"] for item in catalog["voices"]], {"default":"灵小柔"})}}
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("ip", "voice_info")
    FUNCTION = "select"
    CATEGORY = "T8/Ming 3.0"

    def select(self, voice="灵小柔"):
        catalog = json.loads((Path(__file__).parent / "ming_t8/assets/voices.json").read_text(encoding="utf-8"))
        item = next((item for item in catalog["voices"] if item["id"]==voice), None)
        if item is None:
            raise ValueError("没有找到此官方音色ID")
        return voice, json.dumps(item, ensure_ascii=False, indent=2)


class MingT8BatchPlan:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"template": ("MING_T8_REQUEST",),
            "text_or_file_content": ("STRING", {"multiline": True, "default": "第一段文字。\n第二段文字。"}),
            "format": (["long", "txt", "csv", "tsv", "json"],),
            "max_units": ("INT", {"default": 120, "min": 20, "max": 2000}),
            "pause_ms": ("INT", {"default": 250, "min": 0, "max": 60000}),
            "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff, "control_after_generate":False}),
            "flow_steps": ("INT", {"default": 10, "min": 1, "max": 128})}}
    RETURN_TYPES = ("MING_T8_BATCH", "STRING")
    RETURN_NAMES = ("batch", "preview_json")
    FUNCTION = "plan"
    CATEGORY = "T8/Ming 3.0"

    def plan(self, template, text_or_file_content, format="long", max_units=120, pause_ms=250, seed=-1, flow_steps=10):
        if __package__:
            from .ming_t8.batch import preview_batch
        else:
            from ming_t8.batch import preview_batch
        value = preview_batch({**template,"seed":None if seed == -1 else seed,"flow_steps":flow_steps}, text_or_file_content, format, max_units, pause_ms)
        return value["segments"], json.dumps(value, ensure_ascii=False, indent=2)


class MingT8BatchGenerate:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MING_T8_MODEL",), "batch": ("MING_T8_BATCH",)}}
    RETURN_TYPES = ("AUDIO", "MING_T8_TIMELINE", "STRING")
    RETURN_NAMES = ("audio", "timeline", "report")
    FUNCTION = "generate"
    CATEGORY = "T8/Ming 3.0"

    def generate(self, model, batch):
        import torch
        if not isinstance(batch, list) or not 1 <= len(batch) <= 1000:
            raise ValueError("批量需要1到1000个片段")
        _, asr = core_modules()
        asr.unload()
        engine = residency().get_engine(**model)
        chunks, records, cursor = [], [], 0
        for index, segment in enumerate(batch):
            request = TaskRequest.from_dict(segment["request"])
            pause = float(segment.get("pause_ms", 250))
            if not 0 <= pause <= 60000:
                raise ValueError("片段停顿应在0到60000毫秒之间")
            def progress(phase, fraction, message):
                try:
                    import comfy.model_management
                    from comfy.utils import ProgressBar
                    comfy.model_management.throw_exception_if_processing_interrupted()
                    ProgressBar(1000).update_absolute(round((index+fraction)/len(batch)*1000),1000)
                except ImportError:
                    pass
            output, metrics = engine.generate(request, progress=progress)
            wave = output.waveform.detach().cpu().float().reshape(1,1,-1)
            length = wave.shape[-1]
            records.append({"request":request.to_dict(),"text":request.text,"metrics":metrics,
                            "start_ms":round(cursor*1000/engine.sample_rate),"end_ms":round((cursor+length)*1000/engine.sample_rate)})
            chunks.append(wave)
            cursor += length
            if index+1 < len(batch) and pause:
                silence = round(pause*engine.sample_rate/1000)
                chunks.append(torch.zeros(1,1,silence)); cursor += silence
        result = {"segments":records,"audio_seconds":cursor/engine.sample_rate,"timings":"generation_segment_boundaries",
                  "truncated":any(item["metrics"]["truncated"] for item in records),"sample_rate":engine.sample_rate}
        return {"waveform":torch.cat(chunks,dim=-1),"sample_rate":engine.sample_rate},result,json.dumps(result,ensure_ascii=False,indent=2)


class MingT8Transcribe:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audio": ("AUDIO",), "language": (["Auto","Chinese","English","Cantonese","Japanese","Korean","German","French","Spanish","Russian","Portuguese","Italian"],),
                "subtitle_timings": ("BOOLEAN", {"default": True}),
                "context": ("STRING", {"multiline": True,"default":""}),
                "hotwords": ("STRING", {"multiline": True,"default":""})}}
    RETURN_TYPES = ("STRING", "MING_T8_TIMELINE", "STRING")
    RETURN_NAMES = ("text", "timeline", "report")
    FUNCTION = "transcribe"
    CATEGORY = "T8/Ming 3.0"

    def transcribe(self, audio, language="Auto", subtitle_timings=True, context="", hotwords=""):
        reference, _ = MingT8Reference().prepare(audio)
        residency().prepare_asr()
        _, asr = core_modules()
        with residency().asr_cancellation(asr) as cancelled:
            result = asr.transcribe(reference["path"], language=language, subtitle_timings=subtitle_timings, context=context, hotwords=hotwords, cancel_event=cancelled)
        return result["text"], result, json.dumps(result, ensure_ascii=False, indent=2)


class MingT8Subtitles:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"timeline": ("MING_T8_TIMELINE",)}}
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("srt", "vtt")
    FUNCTION = "render"
    CATEGORY = "T8/Ming 3.0"

    def render(self, timeline):
        if __package__:
            from .ming_t8.exports import subtitles
        else:
            from ming_t8.exports import subtitles
        return subtitles(timeline,"srt"), subtitles(timeline,"vtt")


class MingT8Export:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audio": ("AUDIO",), "format": (["wav","flac","mp3"],),
                             "filename_prefix": ("STRING", {"default":"MingT8/voice"})},
                "optional": {"report": ("STRING", {"forceInput":True}), "srt": ("STRING", {"forceInput":True}), "vtt": ("STRING", {"forceInput":True})}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "T8/Ming 3.0"

    def save(self, audio, format="wav", filename_prefix="MingT8/voice", report="", srt="", vtt=""):
        if __package__:
            from .ming_t8.audio import export_audio
        else:
            from ming_t8.audio import export_audio
        result = MingT8Save().save(audio, filename_prefix, report)
        original = Path(result["result"][0])
        target = export_audio(original, format)
        for kind, content in (("srt",srt),("vtt",vtt)):
            if content:
                original.with_suffix("."+kind).write_text(content,encoding="utf-8")
        result["result"] = (str(target),)
        result["ui"]["audio"][0]["filename"] = target.name
        return result


NODE_CLASS_MAPPINGS = {cls.__name__: cls for cls in (MingT8ModelLoader, MingT8Reference, MingT8SpeakerBank,
                       MingT8Task, MingT8Generate, MingT8Decode, MingT8Save, MingT8Unload,
                       MingT8OneClick, MingT8BatchPlan, MingT8BatchGenerate, MingT8Transcribe, MingT8Subtitles, MingT8Export, MingT8Voice)}
NODE_DISPLAY_NAME_MAPPINGS = dict(zip(NODE_CLASS_MAPPINGS, ["Ming T8 · 原生模型加载", "Ming T8 · 参考录音与Confucius",
    "Ming T8 · 添加对话角色", "Ming T8 · 十种官方任务", "Ming T8 · 原生生成", "Ming T8 · 音频解码",
    "Ming T8 · 保存与试听", "Ming T8 · 释放模型", "Ming T8 · 一体配音", "Ming T8 · 长文与批量计划",
    "Ming T8 · 批量生成", "Ming T8 · Confucius原生转写", "Ming T8 · 字幕", "Ming T8 · 音频与字幕导出", "Ming T8 · 官方音色选择"]))
