# 验证记录（第二轮）

环境：Windows，Node v24.22.0（`C:\Program Files\nodejs`，含 corepack），PATH 中没有 pnpm（`where.exe pnpm` 返回“找不到”），Python 3.15 + PySide6。

## 改动
- `dsh-launcher/main.py`：`_start_batch_step` 检查 `_prepare_pnpm_env` 的 ok，pnpm 不可用时把本条及后续条目记为失败（原因“未找到 pnpm”），输出中文错误并结束批次；两处输出读取改用每个子进程一个 `StreamDecoder`。
- `dsh-launcher/proc_utils.py`：新增 `StreamDecoder`（`codecs.getincrementaldecoder`，先 UTF-8，遇非法序列后连同残余字节改按 ANSI 代码页）；新增 `_ansi_encoding()`。
- 验证中发现的新问题：Python 3.15 默认 UTF-8 模式，`locale.getpreferredencoding(False)` 返回 `utf-8`，原 `decode_output` 的 GBK 回退实际不生效。改为优先 `locale.getencoding()`（本机返回 `cp936`）。
- `README.md` / `README.zh.md`：补充 pnpm 查找顺序与 corepack 垫片说明。

## 验证方法
临时脚本（已删除）以 `QT_QPA_PLATFORM=offscreen` 创建 `LauncherWindow`，设置项目根 `c:\AI\deepseek-harness`，直接调用 `_on_install()`（与“安装”按钮相同的代码路径），拦截 `_finish_chain`/`_finish_batch` 记录退出码，并把日志控件全文写入 UTF-8 文件检查。

## 结果
| 场景 | 结果 |
|---|---|
| `python -m py_compile main.py proc_utils.py config.py plugin_manager.py` | 退出码 0 |
| 安装，删除（改名备份）已有垫片，强制走 corepack 生成 | 日志 `[提示] 未找到 pnpm，已通过 corepack 启用（垫片目录 ...\dsh-launcher\pnpm-shim）。`，`Done in 3m 33.5s using pnpm v11.28.5`，`===== [安装] 结束，退出码 0 =====`，U+FFFD 数 0，`✔` 等字符正常 |
| 安装，复用已有垫片 | `Done in 827ms using pnpm v11.28.5`，退出码 0，无 U+FFFD |
| PATH 去掉 nodejs/npm 目录后安装 | `[错误] 未找到 pnpm，也未找到 corepack。请安装 Node.js（含 corepack）后执行 ...`，链条退出码 1，未启动子进程 |
| 同上，批量“检查更新”两个条目 | `[错误] pnpm 不可用，已中止本批次。`，汇总“成功 0 个，失败 2 个”，a/b 原因均为“未找到 pnpm”，未启动子进程 |
| `StreamDecoder` 逐字节喂入 `安装完成，退出码 0` 的 UTF-8 与 GBK 编码 | 两种都还原为原文（修 `getencoding` 前 GBK 结果为替换字符） |
| `decode_output('错误'.encode('gbk'))` | 还原为“错误” |

## 遗留
- corepack 首次生成垫片后下载 pnpm 需要联网，离线会失败（环境限制，启动器给出中文报错）。
- 没有真人点击 GUI 验证；仓库内没有启动器自动化测试。
- 若流前段为纯 ASCII、后段才出现 GBK，切换前已输出部分不受影响；切换后整条流按 ANSI 解码，同一进程混用 UTF-8 与 GBK 输出时后续 UTF-8 中文会乱字（概率低）。
