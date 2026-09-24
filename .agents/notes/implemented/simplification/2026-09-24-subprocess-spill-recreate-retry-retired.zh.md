# Agent Note: 退役子进程 spill 目录重建重试

Status: implemented

[English](2026-09-24-subprocess-spill-recreate-retry-retired.md) | 中文

## 问题

本 fork 在 `dsh-subprocess-local` 中带有自己的 spill 故障容错（[容错决策](../bug-fix/2026-09-15-subprocess-spill-fault-degradation.zh.md)）：`OutputCollector` 会用 `mkdirSync`（recursive、`0o700`）重建私有 spill 目录并重试一次独占打开，因此临时目录被外部清理扫过的宿主仍能继续恢复完整流。随后上游沿另一条路达到了同一个容错目标——`SpillOptions.onFailure`、经 `logSpillFailure` 从所属 logger 打出一行 `error`、用 `spillDisabled` 标志在该 collector 余下生命周期内关闭 spill，以及只在打开成功后才公布 spill 路径，从而绝不 unlink 被植入的条目。在此之上继续保留重建重试，意味着每次合并都要把一段本地分支重新移植进 `output.ts`——一个上游高频改动的文件——并自行维护重建目录与上游永久关闭标志之间的交互。

## 决策

重建重试退役，`dsh-subprocess-local` 整块取上游。spill 打开或写入故障现在会丢弃不完整的 spill、经 `SpillOptions.onFailure` 上报一次、置上 `spillDisabled`，并在该 collector 余下生命周期内让该流只保留内存尾部。

早先那份 note 记录的容错决策不变、且仍然是仓库现实：spill I/O 运行在流的 `'data'` 监听器内，因此绝不能抛出。实现由上游承担，且其容错范围比本 fork 原先更宽；当前机制由[那份 note](../bug-fix/2026-09-15-subprocess-spill-fault-degradation.zh.md) 承载。

这推翻了那份 note 里的一条理由：它当初以「外部临时目录清理在长期运行宿主上反复发生、且目录重建廉价」为由否决了「用一个持久内存标志吞掉所有 spill 错误、不重试」。那条推理描述的损失依然真实，只是被「文件归上游所有」这一点压过。

## 考虑过的替代方案

**把重建重试移植到上游结构上，并补一个对应 spec。** 不予采用：`output.ts` 是上游正在活跃改动的文件，这会带来永久的逐次合并移植成本，还多一层语义交互要维护（`spillDisabled` 已置上之后再重建目录没有作用，因此重试必须跑在上游自己的 catch 之前）。收益只是覆盖一类临时目录故障，而且只关乎一份恢复产物的完整性。

**归档早先那份 note，把全部内容记在这里。** 不予采用：它的容错决策仍是仓库现行契约，而上游没有写自己的 note，归档会让那条理由只剩代码注释与包 README 两处承载。

**改写早先那份 note 里已否决替代方案的推理，让它与实际发布的代码一致。** 不予采用：`implemented/` 的 note 允许订正事实，但不允许回溯改写理由，而那条被否决的替代方案恰恰是将来有人遇到「被清理过的宿主上 spill 不再工作」时最需要读到的推理。因此它的推理原样保留，只补一句说明现行代码已不符合它并指向本 note。

## 后果

在每进程 spill 目录被外部临时文件清理程序删除的宿主上，受影响的 collector 会打出一行 `error` 日志，随后该进程余下时间只保留内存尾部。这些流的完整流恢复在重启前不再可用，而本 fork 原先会静默恢复它。读取仍然可用、宿主继续服务，这正是容错决策要保护的东西。

`OutputCollector` 的签名为上游的 `(maxBytes, label, spill?: SpillOptions)`；本 fork 的 `(maxBytes, maxSpillBytes, label, spillDir)` 形式以及 `newSpillFile` / `openSpillFile` 辅助函数都已不存在。`packages/subprocess/subprocess-local` 现在没有任何本地改动，因此合并时不需要保护。

## 验证

退役后没有本 fork 自有的行为需要覆盖；上游的故障注入用例清单见[那份容错 note](../bug-fix/2026-09-15-subprocess-spill-fault-degradation.zh.md)。`packages/subprocess/subprocess-local` 与上游 tag 完全一致，因此本次需要的证据是「没有别处依赖被删掉的那个签名」：`pnpm run typecheck` 与 `pnpm run build` 在本 fork 上均已实测通过。`tests/spawn.spec.ts` 仍在 win32 被包内 `vitest.config.ts` 排除，其行为证据依旧来自 CI 或 POSIX 宿主——只是这份义务现在归上游，不再归本 fork。
