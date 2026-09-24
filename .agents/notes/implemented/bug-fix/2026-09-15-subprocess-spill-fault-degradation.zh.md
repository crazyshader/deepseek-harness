# Agent Note: 子进程 spill 故障降级

Status: implemented

[English](2026-09-15-subprocess-spill-fault-degradation.md) | 中文

## 问题

一个长期运行的宿主进程（在 `dsh web` 中观察到）因 stderr 收集器流回调内的 `openSync` 抛出未捕获的 `ENOENT` 而崩溃。每进程私有 spill 目录在首次 spawn 时创建一次；该进程存活期间，目录被 OS 临时目录的外部清理删除，随后某条被收集流首次溢出时尝试在已不存在的目录中打开 spill 文件。异常从流的 `data` 事件逃逸，成为未捕获异常，杀死了整个宿主进程——一次尽力而为的输出恢复失败产生了宿主级的爆炸半径。

## 决策

在 `dsh-subprocess-local` 中，创建与写入 spill 文件不再可能从流回调中抛出。`OutputCollector.spillAll` 容错了它可能引发的全部文件系统故障——以随机名独占打开文件、一次性回填已收集块、以及每次逐块 `writeSync`：收集器丢弃不完整的 spill、停止宣传 `spillPath`，并经 `SpillOptions.onFailure` 上报一次错误，与 `seal` 中最终关闭失败的既有容错规则一致。丢弃动作同时置上 `spillDisabled`，因此一次故障就终结该 collector 余下生命周期内的全部 spill，只产出一条上报而不是每个后续块各报一次；该流从此只保留内存尾部。私有 spill 目录每进程只创建一次、不会重建，因此被外部临时文件清理程序删掉的目录会让该进程后续每个 collector 都走同一条降级路径、直到进程重启；而 `ENOSPC`、`EEXIST` 这类单文件故障只损失撞上它的那条流。spill 路径只在打开成功后才记录，因此丢弃动作绝不会 unlink 本进程没有创建过的路径；上报器自身抛出也会被捕获并写入 stderr，而不会变成这条路径本就要防住的未捕获异常。保尾内存缓冲始终保留，因此输出读取仍然可用，宿主进程继续服务。

## 考虑过的替代方案

**用一个持久内存标志吞掉所有 spill 错误、不重试。** 当时不予采用：外部临时目录清理是长期运行宿主上反复发生的事件，而目录重建廉价且安全；因一次瞬时故障就永久失去完整输出恢复是不必要的损失。这条推理与仓库现行代码不符——现行代码用的正是那个持久标志：本 fork 的重建重试已退役，容错由上游承担（[原因](../simplification/2026-09-24-subprocess-spill-recreate-retry-retired.zh.md)）。

**在宿主进程中挂全局 `process.on('uncaughtException')` 处理器。** 不予采用：它会掩盖任意回调中的其他同步抛出并隐藏真实 bug；本修复关闭的崩溃路径是流回调内唯一未容错的 spill I/O。

## 后果

无法创建或写入 spill 文件的流仍以截断的内存尾部结算且不携带 `spillPath`，与最终关闭失败完全一致。这类流的 `readFrom` 只是无法从 spill 文件恢复 lossy 区间。已完成的 spill 文件不受影响；仅属主 `0o700` 目录加 `0o600` 随机名文件让共享临时目录的符号链接植入与路径预测防御保持不变。临时目录确实不可写的宿主对该流失去完整输出恢复，而不再失去整个进程。

## 验证

[spawn 规范](../../../../packages/subprocess/subprocess-local/tests/spawn.spec.ts)中的 `node:fs` 故障注入 mock 带有 `failNextOpen` 与 `failNextWrite` 开关。这些 spec 覆盖了：spill 目录被删除（`ENOENT`）、目录路径实为文件（`ENOTDIR`）、文件已存在后追加失败（`ENOSPC`）、独占打开失败且不得 unlink（`EEXIST`）、上报器自身抛出，以及不带所属 logger 的裸 `spawnSubprocess`。`tests/spawn.spec.ts` 在 win32 被包内 `vitest.config.ts` 排除，因此行为证据来自 CI 或 POSIX 宿主。

本修复关闭的崩溃已在 Windows 上的 `dsh web` 宿主中复现：崩溃运行的 `dsh-subprocess-*` 目录已不在临时目录中，而同级的每进程目录仍在，证实了外部删除这一触发源。
