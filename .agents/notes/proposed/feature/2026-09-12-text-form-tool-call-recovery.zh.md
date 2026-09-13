# Agent Note: Recover a turn that ends on a text-form tool call

Status: proposed

[English](2026-09-12-text-form-tool-call-recovery.md) | 中文

## 问题

模型可能把工具调用写进文本内容，而不是走协议的 `tool_calls` 字段。此时 harness 读到的是一条纯文本 assistant 消息，判定模型已无待答内容，于是关闭轮次。用户看到的是一段原始标记，以及一个没有任何说明就停下的会话。

终止判据位于 [`ReactLoopAgent.step`](../../../../packages/core/agent-loop/src/agent.ts)，它依据内容块类型判断，从不看文本：

```ts ignore-check
if (finish.kind === 'max-tokens') return { kind: 'max-tokens' }

const toolCalls = message.content.filter(block => block.type === 'tool-call')
if (toolCalls.length === 0) return { kind: 'completed' }
```

只有 provider 从协议 `tool_calls` 字段翻译出来的调用才会成为 `tool-call` 块，因此端点留在 `content` 里的调用对这个过滤器不可见。该判据对其自身契约是正确的，保持不变；缺的是一个消费方，去识别「纯文本消息其实是一次失败的工具调用，而不是一个完成的回答」这唯一一种情形。

来自 13 个本地会话的实测证据，全部路由到 `ollama/Qwen3.8-27B`，采样时刻 2026-09-12T02:18:59Z：

| 呈现模式 | 会话数 | assistant 消息数 | 协议工具调用数 | 文本形式工具调用数 | 占比 | 每次之后的轮次结束原因 |
|---|---|---|---|---|---|---|
| `ptc` | 9 | 1538 | 1593 | 6 | 0.39% | `completed` ×6 |
| `native` | 4 | 15 | 14 | 0 | 0.00% | — |

三条事实决定了设计取向。这类失败很少发生，因此模型在重试时会恢复正常，而不是重复同一个错误。每一次发生都以 `completed` 关闭了轮次，因此没有任何报错、日志条目或用户可见信号能把它与一个完成的回答区分开。`native` 的样本只有 15 条消息，无法与 `ptc` 构成对比。

模型输出的标记本身也是畸形的，而且每次畸形方式不同：

```text
</parameter>
</parameter>
</function>
```

```text
<description>
Read 3090 token URL from log
</parameter>
```

第一个样本把 `parameter` 闭合了两次；第二个把 `description` 作为裸标签打开，却用 `parameter` 闭合。两次输出都建立在正确的工具认知之上——输出的 `run_code`、`code`、`description` 三个名称与请求携带的 schema 完全一致——所以模型读到了自己的工具，只错在输出通道。

## 提案

在 `packages/guard/` 下新增 `@deepseek-ai/dsh-text-form-tool-call-recovery`，一个循环卫生插件：监听 `agent/turn-stopping`，要求模型经工具通道重新发出该调用。[agent loop 状态机](../../implemented/simplification/2026-07-24-agent-loop-observable-state-machine.zh.md)定义了这个扩展点：监听器若有异议，就用 `agent.steer()` 记录 steering（中途引导），循环在提交边界前重读收件箱。该插件不需要改动 `agent-loop`。

### 检测

监听器仅在轮次最后一条 assistant 消息同时满足以下全部条件时动作：

- 该消息不含任何 `tool-call` 内容块。已派发调用的轮次不需要恢复。
- 其文本命中某个已配置的标记。默认值覆盖本仓库观察到的标记：`<tool_call>`、`<function=` 和 `<parameter=`。
- 本轮次已执行的恢复次数尚未超过 `maxRecoveriesPerTurn` 允许的上限。

检测读取 `agent.session.deriveMessages()` 并取最后一条 `assistant` 消息，这正是现有 `agent/turn-stopping` 监听器已在使用的访问方式。

### 恢复

监听器调用 `agent.steer(createUserMessage(...))`，纠正消息的来源标注为 `{ kind: 'plugin', plugin: 'text-form-tool-call-recovery' }`。steering 面向下一个步骤并唤醒驱动器，因此同一轮次会再执行一次模型请求而不是关闭。该消息用模型自己的措辞陈述可观察事实：上一条回复用文本描述了一次工具调用，没有工具真正执行，该调用必须经工具调用通道重新发出。

逐轮次的恢复计数存放在按轮次号索引的 `WeakMap<Agent, ...>` 中，与 [repeat-tool-reminder](../../../../packages/guard/repeat-tool-reminder/README.zh.md) 采用的内存内记账方式一致。次数上限是必需的：在该事件上无条件动作的监听器会永久强制续行，这正是 Claude Code 与 Codex 的 hook 桥接把自限次数写为调用方职责的原因。

### 配置

| 字段 | 默认值 | 含义 |
|---|---|---|
| `markers` | `['<tool_call>', '<function=', '<parameter=']` | 用于识别文本形式工具调用的子串 |
| `maxRecoveriesPerTurn` | `1` | 单个轮次因此原因最多可被引导几次 |
| `enabled` | `true` | 监听器是否动作 |

空的 `markers` 列表、小于 1 的 `maxRecoveriesPerTurn`，或非整数的次数，都在插件加载时抛错。配置错误绝不降级为默认值。

### 包结构

| 路径 | 内容 |
|---|---|
| `packages/guard/text-form-tool-call-recovery/package.json` | 清单，照 `repeat-tool-reminder` 的 peer 与 dev 依赖集合 |
| `packages/guard/text-form-tool-call-recovery/tsconfig.json` | 继承 `tsconfig.base.json`，设置 `rootDir: src`、`outDir: lib/types` 与工作区引用 |
| `packages/guard/text-form-tool-call-recovery/src/index.ts` | `name` / `Config` / `apply` 函数式插件导出与监听器 |
| `packages/guard/text-form-tool-call-recovery/README.md` | 包契约、Model Experience 与 Known Limitations 章节 |
| `packages/guard/text-form-tool-call-recovery/tests/` | 单元、释放与真实组合规格 |

该包不发布 `./invariant`：恢复计数私有于单个监听器，不暴露任何可被独立观察的关系。其 README 记录该理由，并把该包加入 `verify-package-invariants` 的允许清单。

是否挂载是部署选择。该插件应与其他循环卫生 guard 一同进入 `base` bundle，因为它覆盖的失败属于模型路由的性质，而不属于某一个 profile。

## 同类先例

针对这类失败存在两条路线，分歧在于修复该落在哪里。

经模型恢复是 [LangChain deepagents 容错指南](https://docs.langchain.com/oss/python/deepagents/fault-tolerance)记载的做法，它把运行时自动重试的瞬时失败与应当回到模型面前的解析失败分开处理。[Wink](https://arxiv.org/html/2602.17037) 报告，定向纠偏在超过 10000 条真实轨迹上解决了 90% 的、单次介入即可修复的 agent 错误行为。两处来源的内容均已改写以符合许可限制。

解析文本是 `goose` 的选择：为 `<function=name>` 形式做了 XML 回退解析器，另有更重的 "toolshim" 路径。它自己的[后续 issue](https://github.com/aaif-goose/goose/issues/8269) 记录了代价——该解析器只处理那一种格式，不处理 Kimi 的格式，于是每个模型家族都变成又一种要支持的格式。

上游缺陷两侧都有记录。[ollama#16686](https://github.com/ollama/ollama/issues/16686) 报告 `qwen3coder` 解析器在模型省略起始 `<tool_call>` 标签时不介入，并把这种省略描述为该模型的已知毛病，整个调用因此以 content 形式抵达客户端。[QwenLM/Qwen3.6#178](https://github.com/QwenLM/Qwen3.6/issues/178) 报告了同一类对 chat template 工具调用格式的偏离，其中包含多余的闭合标签。两者都与上文的畸形样本吻合。

## 考虑过的替代方案

**在 provider 或共享中间件里把文本解析成真实工具调用。** 因三点否决。观察到的输入每次畸形方式都不同，解析器要么拒绝它，要么产出错误参数。在 `ptc` 呈现下唯一可调用的工具是 `run_code`，它执行程序，因此错误参数意味着运行错误的代码——这个后果比多一次模型请求严重得多。而把 Qwen 专有的标记格式放进 provider 翻译层，不对应该 provider 负责的任何契约；`goose` 的后续 issue 展示了随之而来的逐家族维护成本。

**只修模型端点。** 必要但不充分。`ollama#16686` 与 `QwenLM/Qwen3.6#178` 把部分缺陷定位在模型自身的输出上，任何解析器配置都触及不到。修端点能降低发生率，但不能让 harness 在某个路由退化时保持安全。

**改 agent-loop 的终止判据。** 否决。让 `step()` 把可疑文本当作隐式续行，会把一个模型专有的启发式搬进循环的决策路径，使每个消费方都继承它。`agent/turn-stopping` 存在的意义正是让这类策略留在该路径之外。

**只做配置改动：改用 `native` 呈现、降低推理强度，或恢复压缩。** 作为修复方案否决。`native` 样本 15 条消息对 `ptc` 的 1538 条，支撑不了任何结论；而且该失败在一个 32 条消息的会话与一个 671 条消息的会话中都出现过，上下文长度解释不了它。恢复压缩本身值得做——无界上下文最终会超出窗口——但与本缺陷无关。

**在端点前面挂一个外部修复代理。** 作为首选修复方案否决。它有效，已经在跑代理的部署也保留其收益，但它把 harness 的韧性搬进了逐用户的基础设施，且只覆盖该用户代理到的那些路由。

**只上报不恢复。** 单独采用则不充分。把该事件暴露出来消除了静默，那是问题的一半，但轮次仍然死掉、用户仍要重新输入。恢复方案已经涵盖它：被引导的那条消息本身就是记录，带插件来源标注，且可从会话日志重建。

## 验收标准

- 模型发出文本形式工具调用的会话在同一轮次内再执行一个步骤而不关闭，且会话日志携带那条带插件来源的引导消息。
- 同一会话在 `maxRecoveriesPerTurn` 用尽后正常关闭，不会出现超过上限的强制续行。
- 已派发真实工具调用的 assistant 消息绝不触发恢复，文本未命中任何已配置标记的消息同样不触发。
- 空的 `markers` 列表与小于 1 的 `maxRecoveriesPerTurn` 各自在插件加载时失败，报错信息点名该字段。
- 一个真实组合规格经 Loader 引导仅用于测试的 `cordis.yml`，并断言那个额外步骤与被注入的消息，遵循[产品可见插件规则](../../../../packages/AGENTS.md)。
- 一个释放规格释放 fiber 并观察到监听器已被移除。
- 一个录制会话快照固定住模型可见的纠正文本，因为该消息会进入模型请求。
- `pnpm run test`、`pnpm run typecheck`、`pnpm run lint`、`pnpm run hygiene`、`pnpm run doc-sync` 全部通过，且生成的配置目录包含新增的 `Config` 字段。

## 风险

- **强制续行没有终点。** 上限逻辑有缺陷会让监听器变成无限轮次。上限默认为 1、加载时校验，并有规格断言上限用尽后轮次关闭。
- **误判。** 模型正当地讨论这类标记时——引用日志、撰写关于它的文档——会收到一次不必要的纠正。「不含 `tool-call` 块」这一条件排除了常见情形，而一次错误提示的代价是多一次请求。
- **模型可能不配合。** 没有任何机制保证重发的调用会走上协议通道。在 0.39% 的失败率下单次重试极有可能成功，不成功时上限也界定了损失。
- **每次发生多花一次模型请求。** 接受：替代结果是一个死掉的轮次，加上一次人工重试——那次重试花掉同样的请求，还要加上用户的时间。
- **标记默认值会过时。** 默认值覆盖已观察到的标记，而非每个家族；Kimi 的分隔符已知不同。`markers` 因此可配置，新家族是一次配置改动而不是代码改动。
