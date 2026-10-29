# 来源与第三方组件

- Ming 3.0 Tiny 官方算法与协议：[inclusionAI/Ming-3.0-tts](https://github.com/inclusionAI/Ming-3.0-tts)，固定提交 `028c1eace193e7acdb256453da89b6e9207e052b`。MIT 原文见 `ming_t8/_vendor/MING-LICENSE`。
- 官方模型：[inclusionAI/Ming-3.0-tts-tiny](https://huggingface.co/inclusionAI/Ming-3.0-tts-tiny)，revision `7bd9446a8d47e462362261a0150258da6d458318`。
- INT8 ConvRot 格式权重：[Comfy-Org/Ming-3.0-TTS](https://huggingface.co/Comfy-Org/Ming-3.0-TTS)，revision `bfabd8d02bf0410ebb6cff1444d1d7b7b26212e1`。本项目实现自己的加载与计算，不分发 Comfy 的 Ming 推理源码。
- KDA 数学参照：[fla-org/flash-linear-attention](https://github.com/fla-org/flash-linear-attention)，MIT。ConvRot 数学布局参照：[Comfy-Org/comfy-kitchen](https://github.com/Comfy-Org/comfy-kitchen)，Apache-2.0。
- Confucius 原生接口及音频处理：[T8mars/comfyui-confucius-r2t2-t8](https://github.com/T8mars/comfyui-confucius-r2t2-t8)，提交 `9bebc7bb09b2426c43af36b72ac7377f144ac852`，Apache-2.0 原文见 `ming_t8/_vendor/CONFUCIUS-LICENSE`。本项目的接口增加命名空间、关闭与取消功能，未包含 HTTP worker。
- Confucius 模型遵循随包的 NetEase Youdao Model Use License Agreement；与接口代码许可分别保留。GGUF 的 llama.cpp 固定提交 `ad6c66839af3c5646fba8c6c2e2087a1e4e38948`，原始许可随组件提供。
- FireRedVAD 模型许可位于其模型目录 `LICENSE`。语音字幕为段级近似时间，不提供词级对齐。
- [FlashAttention](https://github.com/Dao-AILab/flash-attention) 为 BSD-3-Clause。Windows候选轮子来自 [Rogala/AI_Attention](https://github.com/Rogala/AI_Attention/tree/main/python-3.12/2.8.0%2Bcu128)，SHA256 `04d5f29e3a96a3acac7152f45170c9ed079a1f3708b6ed178967dc6818011f8b`；仅与匹配运行时一起验证和分发。
- Python、PyTorch、Torchaudio、Transformers、ONNX Runtime、NumPy、SciPy、SoundFile、soxr、FastAPI、Triton 和其他依赖的许可保留在运行时包及其 dist-info 中。FFmpeg 按其实际构建随附许可单独保留。
- 演示录音来自固定版本官方仓库的 `data/voice_presets/voice_audio/`。本地新增 CUDA、UI、调度与节点代码的来源记录见 `roadmap.md`。

完整离线包附二进制与模型 SHA256 清单。开发、下载、打包、实际验证是不同状态，以验收记录为准。
