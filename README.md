# Ming 3.0 TTS · T8star

**简体中文** | [English](README.en.md)

Ming 3.0 Tiny 的原生 ComfyUI 节点与本地语音工作台。推理在当前 Python 进程内完成，共用独立核心；转写使用 **Confucius4-R2T2**，不依赖外部推理服务或 Whisper。

[模型下载](https://huggingface.co/t8star/Ming3-TTS-Comfy) · [示例工作流](examples) · [问题反馈](https://github.com/T8mars/Comfyui-Ming3-TTS-T8/issues)

## 程序整合包与更新

[下载程序包](https://github.com/T8mars/Comfyui-Ming3-TTS-T8/releases/latest/download/Ming3-TTS-T8-Program.zip)：包含工作台、节点与必要原生组件，**不包含Python环境和任何模型**。完整运行环境与模型单独准备，配好后双击 `启动工作台.cmd`。

默认自动检查并下载程序更新，关闭工作台后，下次通过启动脚本自动安装。也可在设置中手动检查或关闭自动更新，或关闭工作台后运行 `一键更新.cmd`。更新保留Python、模型、设置、声音库和作品，失败会回滚。[安装与更新说明](docs/program-package.md)。

## 功能

- 完整支持十种任务：内置音色、声音设计、声音克隆、多语种克隆、语气标签、基础属性、情绪、方言、自由指令和多人联合对话。
- 546个官方音色ID及变体；7种语言、14种语气标签、7种情绪、川渝话与广粤话。
- 参考录音裁剪、Confucius转写与字幕；长文批量、逐句导演、停顿、重做、增量播放及多格式导出。
- 17套可编辑工作流；另有粉白工作台，提供声音库、收藏、工程和任务历史。
- 独立加载 Comfy INT8 ConvRot 与官方 BF16 权重。默认采用原生 CUDA＋CUDA Graph＋SDPA；FlashAttention 为可选项。

## 安装

在 ComfyUI-Manager 中搜索 **Ming 3.0 TTS · T8star**，节点ID为 `ming3-tts-t8`，Publisher 为 `t8star`。

手动安装：在 `ComfyUI/custom_nodes` 中执行：

```bash
git clone https://github.com/T8mars/Comfyui-Ming3-TTS-T8.git
cd Comfyui-Ming3-TTS-T8
python -m pip install -r requirements.txt
python install.py
python scripts/fetch_models.py
```

请将 `python` 替换为 **ComfyUI自己的解释器**。`install.py` 仅下载并校验原生组件，不安装Python依赖；模型下载脚本支持缓存复用，并写入本节点的本地路径配置。已有模型时，可直接填写 `settings.example.json` 后另存为 `settings.local.json`，无需重复下载。

重启 ComfyUI，将 `examples/audio` 的示例录音复制到 `ComfyUI/input`，导入 `examples/*.json` 后运行。`.api.json` 为API工作流。

## 使用

常用链路：**模型加载 → 参考准备（按需）→ 任务设置 → 原生生成 → 保存试听**。一体配音节点适合自动转写后克隆。

| 模式 | 输入 |
|---|---|
| 内置音色 / 声音设计 | 官方音色ID / 声音描述，无需录音 |
| 中英文 / 多语种 / 语气标签克隆 | 参考录音与准确的对应文字 |
| 属性 / 情绪 / 方言 | 参考录音与相应控制 |
| 自由指令 | 演绎描述，可选参考录音 |
| 联合对话 | 至少两位角色的有序录音、文字和台词 |

语言选项不翻译正文。联合对话单次最多600帧，约48秒预算；长节目请分场景或使用逐句导演。Confucius字幕采用VAD段级时间，需要校对。

独立工作台请使用GitHub完整源码，另装 `requirements-studio.txt` 后运行 `python studio.py`；Registry节点包不含工作台前端。已取得完整整合包时，双击 `启动工作台.cmd` 即可。

## 兼容与性能

- 当前预编译组件：**Windows x64、Python 3.10 / 3.12、CUDA 12.8**。使用宿主已有的匹配Torch/Torchaudio，不自动替换。
- 本机验证：RTX 5090 Laptop 24GB；Comfy宿主 Python 3.10 / Torch 2.11，独立包 Python 3.12 / Torch 2.8。其他硬件未作同等验收。
- Ming内核包含sm80/86/89/90/100/120；Confucius随包CUDA库为sm120，其他显卡使用其原生CPU路径。其他Python ABI需重新编译识别扩展。
- 同一条2.88秒短句暖机实测：兼容路径9.68–10.61秒，默认加速2.53–2.67秒，约3.6–4.2倍；不代表所有文本或首次加载速度。该负载下Flash组合更慢，因此默认使用SDPA。

已完成十任务、69项生成矩阵、17套真实宿主工作流及本机浏览器验收；八段样本已通过用户听音确认。自动转写检查不代替所有音色和情绪的人工评估。

0.2.2完成新一轮[20轮交叉审查](docs/review-0.2.1.md)，修复更新事务、工程恢复和试听缓存等6类问题；138项Python测试、16组浏览器检查及十任务DOM回归通过。详见[更新记录](CHANGELOG.md)。

## 来源与许可

本项目原始代码采用 [Apache-2.0](LICENSE)。[Ming官方代码](https://github.com/inclusionAI/Ming-3.0-tts)保留MIT许可；[Comfy权重](https://huggingface.co/Comfy-Org/Ming-3.0-TTS)、[Confucius](https://github.com/T8mars/comfyui-confucius-r2t2-t8)及其他组件各自保留原许可，详见 [第三方声明](THIRD_PARTY_NOTICES.md)。

## 社区与资源

[B站](https://space.bilibili.com/385085361) · [YouTube](https://www.youtube.com/@T8star-Aix/) · [API](https://api.seedance.nz/sign-up?aff=5f4w) · [免费画廊](https://www.openzhenzhen.com)

[在线AI应用](https://www.runninghub.ai/zh-cn/user-center/1907375370302308353/userPost?inviteCode=rh-v1121) · [ComfyUI整合包](https://pan.quark.cn/s/264edb7e36bd) · [Hugging Face](https://huggingface.co/t8star)
