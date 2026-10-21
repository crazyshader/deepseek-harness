# OpenViking 项目使用指南（本机部署版）

> 适用对象：本机 DeepSeek Harness（dsh）+ Web GUI（http://localhost:3080）
> 编写日期：2026-09-23 · 基于实测验证通过的部署

---

## 1. 这套东西是什么

OpenViking 是一个**持久化上下文/记忆数据库**：

- **openviking-server**（Python，本机 127.0.0.1:1933）——记忆存储、向量化、语义检索的服务端。数据落在 C:\Users\Administrator\.openviking\data（VikingFS + 本地向量库）。
- **@openviking/dsh-memory-plugin**（已装入 web profile）——运行在 dsh 进程内的 Cordis 插件，负责：
  - 会话开始时注入**用户画像（profile）+ 记忆索引 + 可用技能目录**；
  - 每个模型步骤前（pre-step）做**语义召回**，把相关记忆以 <openviking-context> 块追加到上下文（你现在能读到的那些 memory 块就是它注入的）；
  - 监听 session 事件流**自动捕获** user/assistant 消息作为记忆素材；
  - 桥接 MCP 工具（mcp__openviking__* 前缀），让模型能主动读写记忆。
- **本机配套**：
  - Embedding：本地 GGUF 模型 bge-small-zh-v1.5-f16（512 维，CPU，llama-cpp-python 驱动），纯离线；
  - VLM（L0/L1 摘要提取）：litellm → 本机 ninfer 的 Qwen3.8-27B（http://127.0.0.1:8080/v1），纯本地。

**结论：全链路离线可用，不需要任何云 API key。**

---

## 2. 日常使用（最常用）

### 2.1 开机顺序（重要）

1. **先确认 OpenViking server 在跑**（GUI 的插件依赖它，server 不在时插件的召回会静默降级）：

```powershell
Invoke-RestMethod http://127.0.0.1:1933/health
# 期望: {"status":"ok","healthy":true,...,"auth_mode":"dev"}
```

没在跑就启动（前台或计划任务均可，日志建议落到固定位置）：

```powershell
openviking-server
# 或托管运行，日志写入 C:\Temp\ovserver.log
```

2. **启动 GUI**（web profile 已装插件；插件安装后必须重启 web 进程才生效）：

```powershell
pnpm dsh web --no-open   # 在 E:\ai\deepseek-harness 下执行
```

### 2.2 在 GUI 里怎么用

什么都不用配——**自动发生**的事情：

| 时机 | 行为 |
|---|---|
| 新会话开始 | 注入 profile（你的偏好摘要）+ 记忆索引 + viking:// 技能目录 |
| 每次模型调用前 | 语义召回，把最相关的记忆以 <openviking-context> 注入 |
| 对话过程中 | 自动捕获对话内容，进入待提交队列 |
| 累计 token 超过阈值（默认 20000，commitTokenThreshold）或会话结束 | 服务端做语义提取（L0 摘要约 100 token / L1 概览约 2k token）+ 向量化入库 |

**主动操作**（用自然语言对 agent 说即可，它会调 MCP 工具）：

- "记住：……" → mcp__openviking__remember / write
- "查一下之前我们讨论的 X" → mcp__openviking__find / search
- "把这个文档/仓库/URL 存进记忆" → mcp__openviking__add_resource
- "删掉某条记忆" → mcp__openviking__forget（**永久删除，不可逆**）
- "看看我存了哪些记忆" → mcp__openviking__list / tree

### 2.3 命令行直连 server（不经过 GUI）

```powershell
# 客户端配置已写好: C:\Users\Administrator\.openviking\ovcli.conf (url=http://127.0.0.1:1933)
openviking-server health            # 健康检查（打运行中的 server）
openviking-server doctor            # 本机配置体检（不需要 server 在跑）
```

---

## 3. 记忆在哪个空间 / 多项目怎么区分

### 3.1 身份与空间模型

```
account（本机为 "default"）
 └─ user（本机为 "default"，即 viking://~）
     ├─ viking://~/memories      个人长期记忆（跨项目共享）
     ├─ viking://~/skills        个人技能
     └─ viking://~/peers/<peer> 按"对端"（项目/仓库）隔离的记忆
 └─ viking://resources           全局共享资源库（跨用户）
 └─ viking://agent/skills        账号级共享技能
```

### 3.2 peer = 项目隔离的核心机制

插件会自动计算 **peer ID** 决定当前会话的记忆归属：

- **有 git remote**：用归一化的 remote URL。例如 origin 是 git@github.com:volcengine/OpenViking.git → peer 为 github.com-volcengine-openviking。同一 remote 的多个本地 checkout/克隆都归到同一个 peer——**换电脑、换路径克隆同一仓库，记忆跟着仓库走**。
- **无 git remote**：回退到仓库根路径（或 cwd）派生 peer；再不行则落到 user 级空间 viking://~/memories。

**E:\ai\deepseek-harness 是 git 仓库**，所以在这个目录下的会话记忆自动归到它的 peer 空间，与你在别的项目（如 E:\ai 下其他目录）的记忆天然分开。

**固定/覆盖 peer**（多个仓库想共享同一记忆空间，或 remote 不稳定时）：

```powershell
# 只影响启动它的那个 dsh 进程
$env:OPENVIKING_PEER_ID = "github-com-volcengine-openviking"
pnpm dsh web --no-open
```

注意：DSH 不读 <repo>/.openviking/config.json 里的 peer.id（只有插件的 workspace registry 机制认 workspace 文件），所以 pin 必须走环境变量或 profile 配置。

### 3.3 跨项目共享 vs 隔离

| 需求 | 做法 |
|---|---|
| **默认（推荐）**：各项目 peer 记忆互相隔离，但召回时**跨项目看所有 peer**（全局上下文） | 什么都不用做——OPENVIKING_RECALL_PEER_SCOPE 默认就是 all |
| 严格隔离：只召回**当前项目**的记忆，其他项目一律不可见 | 启动 dsh 前设 $env:OPENVIKING_RECALL_PEER_SCOPE = "actor" |
| 完全共享（所有项目记忆互通，不做 peer 隔离） | 设 $env:OPENVIKING_PEER_ID 为固定值（如 "default"），所有仓库落同一 peer 空间 |
| 主动跨项目引用资料 | 把内容放进 viking://resources/<项目名>/（账号级共享资源库），任何会话的检索都能命中 |

---

## 4. 让某些内容不被记录 / 按仓库开关

### 4.1 整进程或按会话 bypass（不捕获、不召回）

```powershell
# 整个 dsh 进程完全绕过 OpenViking（如跑一次性敏感任务）
$env:OPENVIKING_BYPASS_SESSION = "1"

# 按会话模式匹配：sessionId 或 cwd 命中 glob 即 bypass（可多个，逗号分隔）
$env:OPENVIKING_BYPASS_SESSION_PATTERNS = "*secrets*,*tmp-scratch*"
```

### 4.2 按仓库配置（四层，优先级从高到低）

| 层 | 文件 | 特点 |
|---|---|---|
| 1 | 环境变量（OPENVIKING_*） | 最高 |
| 2 | ~/.openviking/workspaces/<slot>.json | 插件的 workspace registry（手动/安装时生成） |
| 3 | <repo>/.openviking/config.local.json | 个人本机覆盖，**建议放 .gitignore** |
| 4 | <repo>/.openviking/config.json | 团队配置，提交进仓库，随项目走 |

workspace 文件**禁止**出现连接/凭据字段（url、api_key、account 等）和 ${VAR} 形式的环境变量展开——这些只能来自环境变量或 ov.conf。

仓库级示例（提交到 <repo>/.openviking/config.json）：

```json
{
  "version": 1,
  "recall": { "tokenBudget": 2000, "scoreThreshold": 0.35 },
  "capture": {
    "filters": [
      "s|\b\d{16,19}\b|[已脱敏卡号]|g",
      "d|机密代号[：:] *\w+",
      "k|本条是临时草稿，不要记住"
    ]
  },
  "bypass": { "session_patterns": ["*dry-run*"] }
}
```

capture filters 是 sed 风格规则：

- s|模式|替换|g —— 替换（脱敏）；
- d|模式 —— 删除匹配的行/片段；
- k|模式 —— 匹配即整条**跳过**不捕获；
- 规则前可加 user: / assistant: 前缀，限定只作用于某一角色的消息。
- 环境变量等价物：OPENVIKING_CAPTURE_FILTERS / OPENVIKING_RECALL_QUERY_FILTERS。

**典型用法**：某实验仓库不想沉淀记忆 → 在该仓库 .openviking/config.json 里配 bypass，或从该目录启动会话时带 OPENVIKING_BYPASS_SESSION=1。

### 4.3 删除已写入的内容

```
# 让 agent 删（模型侧）：直接说"忘掉 X" → mcp__openviking__forget <uri>
# CLI 删（精确到 URI）：
ov rm viking://user/default/memories/notes/ov-e2e-test.md
# 递归删一个目录：
ov rm --recursive viking://user/default/memories/notes/
```

删除是**永久性**的，没有回收站。对整 peer 空间操作要格外小心。

---

## 5. 运维手册

### 5.1 文件地图（本机实际路径）

| 路径 | 内容 |
|---|---|
| C:\Users\Administrator\.openviking\ov.conf | 服务端配置（server/storage/embedding/vlm） |
| C:\Users\Administrator\.openviking\ovcli.conf | CLI 客户端配置（url + 账号） |
| C:\Users\Administrator\.openviking\data | 全部记忆数据（VikingFS + 向量库 + 队列） |
| C:\Users\Administrator\.cache\openviking\models\bge-small-zh-v1.5-f16.gguf | 本地 embedding 模型（47.9 MB） |
| C:\Users\Administrator\.dsh\profiles\web | web profile（已含插件 v0.5.2） |
| C:\Users\Administrator\AppData\Local\Temp\ovserver.log | server 运行日志 |

### 5.2 健康检查三连

```powershell
openviking-server doctor                                            # 配置/依赖体检
Invoke-RestMethod http://127.0.0.1:1933/health                     # server 存活
pnpm dsh --profile web --dump-config | Select-String openviking   # 插件在位
```

### 5.3 常见故障与对策（本机踩过的坑）

| 症状 | 原因/对策 |
|---|---|
| GUI 里没有任何 openviking 注入 | **web 进程是插件安装前启动的** → 重启 pnpm dsh web |
| 插件安装被 pnpm 拒绝（minimumReleaseAge） | 新发布包受 24 小时年龄限制 → 本 profile 已设 minimumReleaseAge: 0；换 profile 时同样处理，或把包名加进 pnpm-workspace.yaml 的 minimumReleaseAgeExclude |
| 启动报 @deepseek-ai/dsh-llm 不导出 assertNever | profile 里装了旧版 @deepseek-ai/dsh-skill 遮蔽宿主包 → pnpm dsh plugin --profile web why @deepseek-ai/dsh-skill 查清后移除该依赖 |
| 语义召回质量差/不命中 | 看 server 日志 embedding 是否报错；bge-small 是中文小模型，跨语言查询效果有限，用中文查中文记忆效果最好 |
| 下载 HuggingFace 资源失败 | 本机必须走代理 HTTPS_PROXY=http://127.0.0.1:7897；huggingface_hub 对该代理有兼容 bug，直接用 httpx.Client(proxy=...) 下原始文件即可（本次模型就是这么下的） |
| llama-cpp-python 装不上 | PyPI 只有源码包且需编译；从 GitHub Releases 下 llama-cpp-python-0.3.35-py3-none-win_amd64.whl 再 pip install 轮子 |
| 召回分数普遍偏低被过滤 | scoreThreshold 默认 0.35；在 workspace 配置的 recall 段调低 |
| 会话内容没沉淀进记忆 | 内容没到 commitTokenThreshold（默认 2 万 token）且会话未结束 → 正常，长会话或结束后才提交 |
| GPU 显存被 ninfer 占满 | embedding 走 CPU 不受影响；VLM 摘要用 27B 与推理服务共享显存，server 端摘要可能变慢但不会失败 |

### 5.4 卸载

```powershell
# 移除插件（在 profile 目录内执行）
pnpm dsh plugin --profile web remove @openviking/dsh-memory-plugin
# 停 server
Stop-Process -Name openviking-server -ErrorAction SilentlyContinue
# 数据保留在 C:\Users\Administrator\.openviking；想彻底清掉再手动删该目录
```

---

## 6. 一分钟速查

```powershell
# 开机顺序
openviking-server                      # 起 server（建议后台）
pnpm dsh web --no-open                 # 起 GUI（插件随 profile 自动加载）

# 验证
Invoke-RestMethod http://127.0.0.1:1933/health
openviking-server doctor

# 常用环境开关（按需加在启动命令前）
$env:OPENVIKING_RECALL_PEER_SCOPE = "actor"   # 严格项目隔离
$env:OPENVIKING_PEER_ID = "xxx"               # 固定 peer
$env:OPENVIKING_BYPASS_SESSION = "1"          # 本进程不记忆
```

---

## 附：本次安装的关键事实（供排障对照）

- server: openviking-server 0.4.21（Python 3.14，pip 安装于 C:\Python314）
- 插件: @openviking/dsh-memory-plugin@0.5.2（web profile）；dsh 0.1.6-alpha.2 在其 peer 范围内
- 认证: dev 模式（localhost 免 key，account/user = default/default）
- 实测通过: doctor 全绿；write→find 语义检索 80% 召回；headless 冒烟会话成功注入 openviking-context
