# Chrome 127.0.0.1 → localhost 显示地址修复

> 本文档用于在 pull 上游最新代码后，解决合并冲突并重新应用本地修复。
>
> **状态：已在当前 checkout 重新应用（最近一次同步时间见下方"应用记录"）。**

## 问题根因

Chrome/Chromium 对 IP 字面量回环地址（`127.0.0.1`）的 `Origin` 头**剥离端口**：
页面在 `http://127.0.0.1:3080`，但 API 请求的 `Origin` 头变成 `http://127.0.0.1`（无端口）。
DSH 服务端的信任围栏（`api-request-trust.ts`）比较 `new URL(origin).host`（`127.0.0.1`）
与 `hostUrl.host`（`127.0.0.1:3080`），不匹配 → **403 Forbidden**。

`localhost` 不触发此行为，`Origin` 头保留端口 → 匹配 → 200。

相关参考：
- [Discussion #313](https://github.com/deepseek-ai/deepseek-harness/discussions/313)
- [Bug #3106](https://github.com/deepseek-ai/deepseek-harness/discussions/3106)

## 修复策略

**只改显示 URL，不改服务器绑定地址。**
- `LOOPBACK_HOST`（显示/浏览器/prompt）→ `localhost`
- `--host`（服务器绑定）→ 保持 `127.0.0.1`
- 信任围栏 `isLoopbackHostname()` → 同时接受 `localhost` 和 `127.x.x.x`，无需改

## 需要修改的文件（共 15 个）

### 核心源码（1 个）

| 文件 | 改什么 |
|---|---|
| `packages/bundle/web-app/src/index.ts` | `LOOPBACK_HOST` 常量从 `'127.0.0.1'` 改为 `'localhost'`，更新注释 |

具体改动：
```diff
- // Display-only mirror of the webserver schema's loopback host: the address the
- // local URL always prints. Not a source of truth — the schema is.
- const LOOPBACK_HOST = '127.0.0.1'
+ // Display-only mirror of the webserver schema's loopback host: the address the
+ // local URL always prints. Not a source of truth — the schema is.
+ // Use `localhost` rather than `127.0.0.1`: Chrome strips the port from the
+ // Origin header for IP-literal loopback addresses, breaking the trust fence's
+ // same-origin check (`new URL(origin).host !== hostUrl.host`). The `localhost`
+ // hostname does not trigger this behavior, so API calls and WebSocket
+ // connections work without 403.
+ const LOOPBACK_HOST = 'localhost'
```

### 测试文件（3 个）

| 文件 | 改什么 |
|---|---|
| `packages/bundle/web-app/tests/web-app.spec.ts` | 所有 `http://127.0.0.1:4567` → `http://localhost:4567`（约 17 处） |
| `packages/bundle/web-app/tests/browser-open.spec.ts` | `http://127.0.0.1:${...}` → `http://localhost:${...}`（1 处） |
| `apps/cli/tests/web-browser-open.snapshot.ts` | 正则 `/http:\/\/127\.0\.0\.1:\d+/` → `/http:\/\/localhost:\d+/`，快照值 `http://127.0.0.1:{{port}}` → `http://localhost:{{port}}`（共约 8 处） |

> **技巧**：对 `web-app.spec.ts` 和 `web-browser-open.snapshot.ts` 可以直接
> `sed` 或 IDE 全局替换 `127.0.0.1` → `localhost`（仅限这些文件中
> `http://` 开头的 URL 上下文）。

### 就绪检测 / CI 脚本（2 个）

| 文件 | 改什么 |
|---|---|
| `apps/cli/tests/lazy-search-startup.compat.spec.ts` | 两处就绪正则 `dsh web: http://127\.0\.0\.1:\d+` → `dsh web: http://localhost:\d+` |
| `scripts/publish-npm-baseline.ts` | Python 探针就绪检测 `b"dsh web: http://127.0.0.1:"` → `b"dsh web: http://localhost:"` |

> ⚠️ 这两处容易被遗漏。如果上游更新了这些文件，冲突解决后**务必重新检查**。

### 文档（8 个）

| 文件 | 改什么 |
|---|---|
| `README.md` | `http://127.0.0.1:3080` → `http://localhost:3080` |
| `README.zh.md` | 同上 |
| `apps/cli/reference/README.md` | 同上 |
| `apps/cli/reference/README.zh.md` | 同上 |
| `docs/user/develop/basic/index.md` | 同上 |
| `docs/user/develop/basic/index.zh.md` | 同上 |
| `docs/user/develop/basic/tool.md` | 同上 |
| `docs/user/develop/basic/tool.zh.md` | 同上 |

> 文档改动最简单：全局搜索 `http://127.0.0.1:3080` 替换为 `http://localhost:3080`。

### 翻译快照（1 个）

| 文件 | 改什么 |
|---|---|
| `scripts/snapshots/translation-prompt-v4/request-response.expected.json` | 内部嵌入的 README 全文中 `http://127.0.0.1:3080` → `http://localhost:3080`（2 处） |

> 如果上游重新生成了翻译快照，直接采用上游版本即可（因为上游 README 仍用
> `127.0.0.1`，快照匹配上游 README）。**仅当本地 README 已改为 `localhost` 时才需要改快照。**

## 不需要改的文件（容易误判）

| 文件 / 位置 | 为什么不改 |
|---|---|
| `packages/bundle/web-app/src/startup.ts` — `--host 0.0.0.0` 错误提示中的 `127.0.0.1` | 这是**服务器绑定地址**建议，必须用 IP 字面量 |
| `packages/bundle/web-app/cordis.patch.yml` — `host: ... ?? '127.0.0.1'` | 服务器绑定默认值 |
| `scripts/publish-npm-baseline.ts` — `--host 127.0.0.1` 参数 | 服务器绑定参数 |
| `apps/cli/tests/built-bin.e2e.ts` — 错误提示中的 `127.0.0.1` | 服务器绑定建议 |
| `packages/host/webserver/src/index.ts` — schema 中 `z.const('127.0.0.1')` | 服务器绑定 schema |
| 各 `llm-*` / `mcp-*` / `subagent-*` 测试 fixture 中的 `127.0.0.1` | 无关的 mock 服务器地址 |

**判断标准**：如果 `127.0.0.1` 是**传给 `--host` 参数**或**服务器绑定**的，不改；
如果是**显示给用户看的 URL**（终端打印、浏览器打开、system prompt、文档），改。

## 合并冲突处理流程

```
1. git pull origin main
2. 如果出现冲突：
   a. 对每个冲突文件，采用上游版本（git checkout --theirs <file>）
   b. 按照本文档"需要修改的文件"列表，重新应用本地改动
   c. 核心源码 index.ts 如果上游也改了注释，保留上游注释，只改常量值和新增注释
3. 全局验证：
   grep -r "http://127.0.0.1:3080" . --include="*.ts" --include="*.md" --include="*.json"
   grep -r "dsh web.*127.0.0.1" . --include="*.ts"
   grep -r "http://127.0.0.1:3080" . --include="*.md"
   → 应该没有结果
4. 运行测试：
   pnpm vitest run packages/bundle/web-app/tests/ --config vitest.config.ts
   → 20 tests passed
5. 提交：
   git add -A && git commit -m "fix: use localhost for display URL (Chrome Origin port stripping)"
```

## 快速验证命令

```bash
# 启动后检查终端输出应包含 localhost
grep "dsh web:" | grep "localhost"

# 检查浏览器打开的 URL
# 应该自动打开 http://localhost:3080 而不是 http://127.0.0.1:3080

# 在浏览器 DevTools Console 中确认无 403 错误
```

## 应用记录

- 上游 pull 后本地修改与最新源码冲突，已 revert 旧改动，并按本文档在最新源码上重新应用。
- 已修改的 15 个文件与本文档列表一致（核心源码 1、测试 3、就绪检测/CI 脚本 2、文档 8、翻译快照 1）。
- 全局验证：`grep -r "http://127.0.0.1:3080"`（`*.ts` `*.md` `*.json`）与 `grep -r "dsh web.*127.0.0.1"`（`*.ts`）均无匹配。
- 已核实 `isLoopbackHostname()`（`packages/client/connection/src/loopback-hostname.ts`）本身已同时接受 `localhost` 与 `127.x.x.x`，无需改动。
- 已运行并通过：
  - `pnpm vitest run packages/bundle/web-app/tests/` — 21 tests passed
  - `pnpm vitest run apps/cli/tests/args.spec.ts apps/cli/tests/web-browser-open.expected.e2e.ts` — 6 tests passed
  - `pnpm vitest run scripts/translation-prompt.expected.spec.ts` — 1 test passed
- 其余检索到的 `127.0.0.1` 均为"不需要改的文件"清单中列出的服务器绑定地址、mock 服务器地址或无关 fixture，未作修改。
