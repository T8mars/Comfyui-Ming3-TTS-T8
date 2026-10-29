# Changelog

## 0.2.0 · 2026-10-29

- 发布独立程序整合包：含工作台、节点和必要原生组件，不含Python环境、模型或用户数据。
- 启动后自动检查并下载更新，下次通过启动脚本安装；提供设置开关、手动检查和一键更新脚本。
- 使用GitHub发布资产SHA256和逐文件清单校验；安装需要工作台完全退出，支持失败回滚和中断恢复。
- 更新保留运行环境、模型、设置、数据库与作品；不自动安装Python依赖。移除开发机器D盘默认路径。

- Publish a program-only bundle with studio, nodes and native components; no Python environment, models or user data.
- Check and download automatically, apply at the next launcher start, or use the manual update controls/script.
- Verify the GitHub asset digest and every file; require the studio to close before installation, with rollback and interrupted-install recovery.
- Preserve environments, models, settings, databases and outputs. Python dependencies are managed separately; remove development-drive defaults.

## 0.1.1 · 2026-10-29

**中文**

- 修复参考音频替换、裁剪和清除后的旧转写残留，以及晚返回请求恢复旧录音的问题。
- 修复收藏音色被已有草稿覆盖、关闭角色选择框后目标残留的问题。
- 修复CPU识别前错误申请CUDA显存、连续标点丢失，以及超过1000条历史记录时的任务恢复遗漏。
- 拒绝为截断音频导出含未生成全文的字幕；损坏工程提供明确错误提示。
- 修复并发安装临时文件冲突、并发设置保存竞争，以及取消下载时进程恰好退出的异常。
- 验证：64项Python测试、十任务DOM回归、参考录音状态回归、真实Edge桌面与390px界面检查。

**English**

- Clear stale transcripts after replacing, cropping or removing reference audio; ignore obsolete asynchronous results.
- Keep a selected saved voice when restoring drafts, and clear role destinations when pickers close.
- Avoid CUDA memory requests for CPU ASR, preserve repeated punctuation and recover active jobs beyond 1,000 history records.
- Reject misleading full-text subtitles for truncated audio and report damaged projects clearly.
- Fix component installation and settings write races, plus download cancellation when the child process has already exited.
- Validation: 64 Python tests, ten-task DOM checks, reference state regressions and real Edge desktop/390px browser checks.

## 0.1.0 · 2026-10-29

Initial public release: native Ming Tiny ComfyUI nodes, local studio, Confucius transcription and pinned model/component installation.
