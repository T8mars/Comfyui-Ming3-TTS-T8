# Changelog

## 0.2.2 · 2026-10-29

- 更新前拒绝文件/目录结构冲突，避免半更新破坏回滚；此类结构迁移需解压到独立目录。
- 备份或事务日志准备失败时，确认旧程序完整后仍可启动；提交/回滚后记录暂时无法删除，不再阻挡完整程序或重复安装。
- 工程省略参数恢复官方默认；带角色信息但无界面元数据的Podcast保留台词和角色名。
- 丢失、损坏或被改动的试听缓存自动重新生成；新片段保存输出SHA256，旧无哈希记录保守重新生成。
- 验证：138项Python测试、16组真实Edge检查、十任务/参考状态DOM；Windows真实元数据句柄占用恢复通过。

- Reject incompatible file/directory layouts before mutation; migrate these releases into a separate folder.
- Keep a verified old program usable after preparation failures; locked post-commit/rollback metadata no longer blocks a complete program or triggers repeated installation.
- Restore omitted project controls to official defaults and retain Podcast scripts/names without UI metadata.
- Regenerate missing, damaged or modified take caches; record output SHA256 for new segments and regenerate older unhashed records.
- Validation: 138 Python tests, 16 real Edge checks, task/reference DOM and real Windows metadata-handle locks.

## 0.2.1 · 2026-10-29

- 修复Windows仅大小写变化的文件改名更新；继续拒绝真实目录链接越界。
- 损坏或丢失的待更新内容仅在确认旧程序完整后隔离，避免阻止完好旧版启动；恢复失败仍停止安装。
- 自动回收已用/失败更新缓存，仅保留一份最新可确认归属的备份，保护未决事务和未知目录。
- 修复取消与完成并发导致“取消中”卡住，以及保存设置/释放模型与任务启动的竞争。
- 修复200条历史上限造成旧任务进度/回调丢失、无效任务输入返回内部错误，以及工程载入残留旧转写。
- 验证：121项Python测试、14组真实Edge检查、十任务和参考状态DOM回归；本轮未重跑GPU音质矩阵。

- Support Windows filename case changes while continuing to reject real path redirection.
- Quarantine unusable pending updates only after verifying the old program; failed recovery still stops safely.
- Reclaim owned update caches, retain one latest backup, and protect pending transactions and unknown directories.
- Fix cancellation/completion and settings/model-release races, missing old-job polling, invalid job validation and stale project transcripts.
- Validation: 121 Python tests, 14 real Edge checks and task/reference DOM checks. No new GPU synthesis matrix in this review.

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
