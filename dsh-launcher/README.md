# dsh-launcher

DeepSeek Harness 的图形启动器。主窗口分两个页签：「控制」提供安装、构建、启动、停止四个操作并实时显示底层命令的日志输出；「插件」提供 web profile 的第三方插件安装/卸载，以及插件兼容性问题导致 DSH 无法启动时的恢复手段。功能与项目根的 `quick-start.bat` 对齐，用 PySide6 实现，可用 PyInstaller 打包成独立 exe。

## 功能

### 控制页签

| 按钮 | 执行的命令 |
|------|-----------|
| 安装 | `pnpm install` |
| 构建 | `pnpm run clean` 然后 `pnpm run build`（两步，任一步失败即中止） |
| 启动 | `pnpm dsh web --port <port>`（常驻 Web 服务） |
| 停止 | 杀掉整棵进程树（`taskkill /T /F`），释放端口 |

其他行为：

- **项目目录**：首次运行需选择 DeepSeek Harness 项目根目录，之后记住（配置存于 `%APPDATA%\dsh-launcher\config.json`）。
- **端口**：可配置，默认 3080，与配置一起持久化。
- **启动后打开 Web**：勾选时，服务就绪后自动打开 `http://localhost:<port>`。
- **幂等启动**：启动前探测目标端口，若被占用（无论来源）先清理占用进程，避免端口冲突导致启动失败。
- **单任务互斥**：同一时刻只允许一个任务运行，运行中其他操作按钮置灰（插件页签的按钮同样受此约束）。
- **前置软提示**：缺少 `node_modules` 或未构建 Web 前端时给出提示，而非硬锁按钮。
- **关闭窗口**：若仍有服务在跑，会提示是否停止后退出。
- **密钥**：不处理 `DEEPSEEK_API_KEY`，继承项目根 `.env`。若未配置，dsh 自身会在日志中报错。

### 插件页签

管理对象固定为 `web` profile（`$DSH_HOME/profiles/web`，`DSH_HOME` 缺省 `~/.dsh`）。插件的安装/卸载走官方机制 `dsh plugin --profile web add|remove <spec>`（转发 pnpm 并维护 `dsh.profile.bundles` 层列表）；用户自有的 `cordis.patch.yml`（如 MCP servers）不受任何影响。

**安装**

- 输入框接受任意 pnpm 依赖 spec：npm 包名（可带版本）、`github:owner/repo`（可带 `#commit`）、本地 `.tgz` 包、本地目录。
- 「目录…」「包…」按钮选择本地插件源码目录或压缩包，回填绝对路径；选目录按 link 语义安装（源码改动重启即生效）。
- 每次经启动器安装前自动拍摄**安装前快照**（见下），日志会记录快照名。
- git 源首次安装若因 pnpm 构建授权（`allowBuilds`）失败，dsh 会在日志里给出修法，按提示改完 profile 的 `pnpm-workspace.yaml` 后重新点安装即可；启动器不自动代做这项授权。

**卸载**

- 列表展示已装的第三方插件（内置 `dsh-base`/`dsh-web-app` 不可卸载）。
- 「卸载选中」只卸载不重启；「卸载选中并重试」「卸载最近并重试」卸载后自动重启 Web 服务（先停当前服务，再执行恢复链条）。
- 卸载不拍快照；误卸载后用安装按钮重装（版本按包名重新解析）。

**安装前快照与回滚（故障恢复）**

- 快照内容：profile 目录的 `package.json`、`pnpm-lock.yaml`、`pnpm-workspace.yaml` 三个文件，存于 `$DSH_HOME/profiles/.dsh-plugin-snapshots/web/<时间戳>/`（profile 目录之外），每份附带「当时正在安装哪个插件」的记录；最多保留最近 5 份，超出删最旧。不拷 `node_modules`（还原后用 `pnpm install` 重建）。
- 插件兼容性问题导致 DSH 无法启动、Web 打不开时，在插件页签手动执行恢复动作（启动器不做自动失败判定，由使用者判断）：
  1. **卸载最近并重试**——卸载最近安装的第三方插件后重启；
  2. **回滚到最新/选中并重试**——把 profile 的 manifest 文件还原到某份快照记录的状态（快照中未记录的文件会删除，完整回到安装前），然后在 profile 目录跑 `pnpm install` 重建依赖，用 `dsh --profile web --dump-config` 验证配置组合可加载，最后重启 Web 服务。
- 恢复链条任一步失败即中止后续步骤（不会带病重启），全过程见日志。
- 回滚链条的 `pnpm install` 一步需要网络（registry 依赖），离线时会停在该步。
- 即使 profile 的 `package.json` 被损坏到 `dsh plugin` 都无法运行的程度，回滚仍然有效——它只做文件还原 + `pnpm install`，不依赖 `dsh plugin`。

## 开发运行

```powershell
# 在 dsh-launcher 目录下
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## 打包成 exe

**双击 `build.bat`** 即可：自动找 Python（`python` 或 `py -3`）、缺 PyInstaller 时自动安装、运行打包、成功后打开 `dist` 输出目录，窗口最后停住便于查看结果。

也可手动执行：

```powershell
pip install pyinstaller
python build.py
```

产物为 `dist/dsh-launcher.exe`，双击即用，无需目标机器安装 Python。若旧 exe 正在运行会导致打包失败（产物被占用），先关掉再打。

## 依赖

- Python 3.9+
- PySide6（见 `requirements.txt`）
- 目标机器需已安装 `pnpm` 且在 PATH 中（启动器只是调用它）

## 平台

仅支持 Windows：进程树清理与端口探测依赖 `taskkill` / `netstat`。
