# Ming 3.0 TTS · T8star

[简体中文](README.md) | **English**

Native ComfyUI nodes and a local speech studio for Ming 3.0 Tiny. Both run the shared inference core inside the current Python process. Speech recognition uses **Confucius4-R2T2**, without an external inference service or Whisper.

[Models](https://huggingface.co/t8star/Ming3-TTS-Comfy) · [Example workflows](examples) · [Issues](https://github.com/T8mars/Comfyui-Ming3-TTS-T8/issues)

## Program bundle and updates

[Download the program bundle](https://github.com/T8mars/Comfyui-Ming3-TTS-T8/releases/latest/download/Ming3-TTS-T8-Program.zip). It includes the studio, nodes and required native components, **without a Python environment or model files**. Prepare the separate environment and models, then run `启动工作台.cmd`.

The studio checks for and downloads program updates automatically. Close it and use the launcher again to install. Settings provide manual checks and an automatic-update switch; `一键更新.cmd` updates while the studio is closed. Updates preserve Python, models, settings, voices and outputs, with rollback on failure. See the [setup and update guide](docs/program-package.md).

## Features

- All ten tasks: preset voices, voice design, cloning, multilingual cloning, paralinguistic tags, basic attributes, emotions, dialects, freeform instructions and joint dialogue.
- 546 official voice IDs and variants; 7 languages, 14 tags, 7 emotions, Sichuan–Chongqing Mandarin and Cantonese.
- Reference trimming, Confucius transcription/subtitles, long-text batches, per-line directing, pauses, regeneration, incremental playback and multiple export formats.
- 17 editable workflows and a pink-and-white studio with saved voices, favorites, projects and job history.
- Independent Comfy INT8 ConvRot and original BF16 loading. Native CUDA, CUDA Graphs and SDPA are the default; FlashAttention is optional.

## Installation

Search for **Ming 3.0 TTS · T8star** in ComfyUI-Manager. Node ID: `ming3-tts-t8`; Publisher: `t8star`.

For a manual installation, run inside `ComfyUI/custom_nodes`:

```bash
git clone https://github.com/T8mars/Comfyui-Ming3-TTS-T8.git
cd Comfyui-Ming3-TTS-T8
python -m pip install -r requirements.txt
python install.py
python scripts/fetch_models.py
```

Replace `python` with **ComfyUI's own interpreter**. `install.py` downloads and verifies native components only; it does not install Python dependencies. The model script reuses cached files and writes this node's local path configuration. To reuse existing models, copy `settings.example.json` to `settings.local.json` and set the paths instead.

Restart ComfyUI. Copy the recordings from `examples/audio` into `ComfyUI/input`, then load an editable `examples/*.json` workflow. Files ending in `.api.json` are API graphs.

## Usage

Typical chain: **Model loader → Reference preparation, if needed → Task settings → Native generation → Save/play**. The all-in-one node handles automatic reference transcription and cloning.

| Mode | Input |
|---|---|
| Preset / voice design | Official voice ID / voice description; no recording |
| Cloning / multilingual / tags | Reference recording and matching transcript |
| Attributes / emotion / dialect | Reference recording and the corresponding control |
| Freeform | Acting instructions, with an optional reference |
| Joint dialogue | Ordered recordings, transcripts and dialogue for at least two speakers |

Language selection does not translate text. Joint dialogue has a maximum budget of 600 frames, approximately 48 seconds per call. Split longer programs into scenes or use per-line directing. Confucius subtitles use approximate VAD segment timings and need review.

For the standalone studio, use the full GitHub source, additionally install `requirements-studio.txt` and run `python studio.py`. The Registry node package excludes the studio frontend. In a complete portable bundle, double-click `启动工作台.cmd`.

## Compatibility and performance

- Prebuilt components: **Windows x64, Python 3.10 / 3.12, CUDA 12.8**. Keep the host's matching Torch/Torchaudio installation; it is not replaced automatically.
- Validated locally on an RTX 5090 Laptop with 24GB VRAM: Comfy host Python 3.10 / Torch 2.11; standalone Python 3.12 / Torch 2.8. Other hardware has not received equivalent validation.
- Ming kernels include sm80/86/89/90/100/120. The supplied Confucius CUDA library targets sm120 and uses its native CPU path on other GPUs. Other Python ABIs require rebuilding the recognition extension.
- Warm runs of the same 2.88-second sentence took 9.68–10.61 seconds with the compatibility path and 2.53–2.67 seconds with the default acceleration, approximately 3.6–4.2× faster. This does not predict all texts or cold starts. Flash was slower for this workload, so SDPA remains the default.

Validation covers ten tasks, a 69-case generation matrix, 17 executed Comfy workflows and local browser interaction. Eight audio samples passed user listening review; automatic transcription does not establish perceptual quality for every voice or emotion.

Version 0.2.1 fixes 8 issues from a new [20-round cross-review](docs/review-0.2.0.md), covering update recovery, cache growth, job races and project state. All 121 Python tests, 14 browser checks and ten-task DOM checks pass. See the [changelog](CHANGELOG.md).

## Attribution and licenses

Original project code is [Apache-2.0](LICENSE). [Upstream Ming code](https://github.com/inclusionAI/Ming-3.0-tts) retains MIT; [Comfy weights](https://huggingface.co/Comfy-Org/Ming-3.0-TTS), [Confucius](https://github.com/T8mars/comfyui-confucius-r2t2-t8) and other components retain their respective licenses. See [third-party notices](THIRD_PARTY_NOTICES.md).

## Community and resources

[Bilibili](https://space.bilibili.com/385085361) · [YouTube](https://www.youtube.com/@T8star-Aix/) · [API](https://api.seedance.nz/sign-up?aff=5f4w) · [Free gallery](https://www.openzhenzhen.com)

[Online AI apps](https://www.runninghub.ai/zh-cn/user-center/1907375370302308353/userPost?inviteCode=rh-v1121) · [ComfyUI bundle](https://pan.quark.cn/s/264edb7e36bd) · [Hugging Face](https://huggingface.co/t8star)
