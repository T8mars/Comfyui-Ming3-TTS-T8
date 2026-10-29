# 程序整合包 / Program bundle

Release中的 `Ming3-TTS-T8-Program.zip` 只含程序、界面、节点、示例及必要原生DLL/PYD/FFmpeg组件，不含Python解释器、Python依赖环境、Ming/Confucius/VAD模型或用户数据。完整运行环境与模型单独配置。它与Registry中的纯节点ZIP用途不同。

## 第一次使用

1. 解压程序包到独立文件夹。
2. 将配套Python环境放入 `runtime`（应有 `runtime/python.exe`），或使用 `runtime/Scripts/python.exe` / `python_embeded/python.exe`。也可设置环境变量 `MING_PYTHON` 指向已有解释器。不要只放一个裸Python解释器，环境须具备Torch及 `requirements-studio.txt` 中的依赖。
3. 配套模型单独放置；可在工作台设置中选择主模型、Ming辅助目录和Confucius目录。已有模型无需重复下载。
4. 双击 `启动工作台.cmd`，在浏览器中使用。

当前预编译组件支持Windows x64、Python 3.10/3.12。推荐沿用已验证的Python 3.12、Torch 2.8 + CUDA 12.8配套环境；完整环境由发布者单独提供。模型见[Hugging Face](https://huggingface.co/t8star/Ming3-TTS-Comfy)。已有配套环境时，`python scripts/fetch_models.py` 可下载并校验模型、配置路径。

## 自动更新

程序包启动后默认在后台检查GitHub正式Release。有新版本时下载程序ZIP，校验GitHub资产SHA256、内部版本和每个文件的大小/SHA256。下载成功后，设置页提示“关闭工作台后重新启动即可安装”。

关闭工作台的终端窗口，再双击 `启动工作台.cmd`。启动脚本先安装已下载的更新，再启动工作台，不会强行中断正在生成的音频。直接运行 `python studio.py` 的开发方式不会执行这个启动前安装步骤。

设置页可手动检查/下载，也可关闭自动更新以离线使用。工作台关闭时还可运行 `一键更新.cmd`，一次完成检查、下载、校验和安装。网络不可用只影响检查与下载，保留当前程序。

更新只允许程序清单中的路径。`runtime`、`python_embeded`、`data`、模型目录、`settings.local.json`、缓存、声音库、任务数据库与作品均不在更新范围。不自动升级或安装Python依赖。未来版本如需调整配套环境，会在Release说明中单独标明。

安装失败会恢复原程序；中途退出后，下次启动先恢复未完成事务。备份和事务保留在 `.updates`，不要在安装过程中删除该目录。DLL被其他程序占用时，请先关闭使用相同组件的程序后重试。旧完整包升级前同样应先关闭工作台，再解压此程序包覆盖程序文件。

0.2.1起，损坏的待更新记录会在确认旧程序逐文件完整后隔离，允许继续使用旧版。已用缓存自动回收，通常只保留一份最新程序备份；未决事务依赖、未知目录和目录链接不会被清理。清理失败会留待下次重试，不撤销成功安装。

更新使用固定的本仓库[GitHub Release API](https://docs.github.com/en/rest/releases/releases#get-the-latest-release)，不接受用户输入的第三方更新地址。

## English

The Release program ZIP includes application sources, UI, nodes, examples and native components. It excludes Python, Python packages, all models and user data. Supply a compatible environment under `runtime` or `python_embeded`, or set `MING_PYTHON`; configure existing model paths in Settings, then use `启动工作台.cmd`.

Automatic updates check stable releases and stage a verified program ZIP. Close the studio and use the launcher again to apply it. Settings allow manual checks/downloads or disabling automatic updates; `一键更新.cmd` performs an update with the studio closed. Direct `python studio.py` runs do not apply staged updates.

The updater verifies the release asset digest and every manifest file, preserves environments/models/settings/voices/outputs, and never installs Python dependencies. Failed or interrupted installations restore the old program. Keep `.updates` while an installation is in progress. Close applications holding native DLLs before retrying. Network failures leave the installed program usable.
