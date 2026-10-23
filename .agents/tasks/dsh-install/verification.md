# 验证记录

| 命令 | 结果 |
| --- | --- |
| `python -m py_compile dsh-launcher/main.py dsh-launcher/proc_utils.py` | 通过，退出码 0 |
| `decode_output('不是内部或外部命令'.encode('gbk'))` | 输出正确中文 |
| `decode_output('中文'.encode('utf-8'))` | 输出正确中文 |
| `ensure_pnpm_path()`（本机无 pnpm） | 通过 corepack 生成 `%APPDATA%\dsh-launcher\pnpm-shim`，返回可用 |
| 在返回目录加入 PATH 后 `pnpm --version`（shell） | `11.28.5`，退出码 0 |
| 再次调用 `ensure_pnpm_path()` | 垫片已存在，直接复用，无提示 |
| PATH 仅含 System32 时调用 `ensure_pnpm_path()` | 返回中文错误“未找到 pnpm，也未找到 corepack……”，ok=False |

说明：首次运行发现 `subprocess` 无法直接执行 `corepack`（.cmd），已改用 `shutil.which` 的完整路径，复测通过。
未做 GUI 手动点击验证；启动器无自动化测试和类型检查配置。未实现方案 4.3（失败提示）与 4.4（README）。
