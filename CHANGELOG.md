# Changelog

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
