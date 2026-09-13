# Agent Note: 批次体积设上限，PDF.js 资源移出 bundle

Status: implemented

[English](2026-09-12-pdfjs-assets-out-of-bundle.md) | 中文

## Problem

一个 combo 批次是单个 `<script>`，里面用 `;` 把多个插件 factory 拼接在一起。这让它成为全有或全无：第一处不完整的语句会让同一文件里后续所有 `__ModuleLoader__.load` 都不再执行，而浏览器仍然触发 `load`——未捕获异常不算脚本加载失败。模块系统于是只能报出它唯一能看见的事实：某个 row 没被注册；真正的错误留在 console 里。

批次划分只约束了请求 URL（3 KiB），从不约束响应体。于是某次部署把全部 59 个 application row 作为单个 12.6 MB 脚本提供。一个浏览器扩展拦下该脚本、重新取回、再用 `eval` 重放，在 99.11% 处把内容截断，整个页面启动失败，而报错信息指向了错误的子系统。

仅设体积上限还不够。`ui-sidebar-documentpreview` 单包 6,888,196 字节且无法切分：其中 85% 是以 base64 和 JS 字符串内联的 PDF.js 二进制数据，占整个 12.6 MB 客户端的 47%。经二分法实测，这一个包仍然超过截断阈值，而体积在约 1 MiB 及以下的批次全部完整到达。

## Decision

**批次同时受响应字节数与 URL 长度约束。** `MAX_COMBO_BODY_BYTES` 为 1 MiB。两个上限的区别在于是否让步：URL 无法寻址会让组合失败，而大于体积上限的 bundle 仍然可寻址，于是自成一批而不失败。graph 顺序保持不变，因此批次边界绝不会把被请求的模块排到其消费者之后。

**`clientModules` 提供包自有的静态资产。** `registerAssets(id, assets)` 把字节发布在 `/plugins/<id>/assets/<path>`，并返回恰好对应它新增路径的 disposer。这复用了每个部署都已经在应答的那个载体：Web 前缀路由与 shell 的 `fetchBundle`——后者正是 Electron 在禁用 `webserver` 的情况下提供 `/plugins/` 的方式。于是包可以把二进制资源放在 JavaScript 之外，既不必自持路由，也不需要任何逐载体的接线。

资产只按 pathname 匹配。它们由所属依赖定版而非由内容 revision 定版，因此版本只作为缓存分离的查询键传递，遗留的键会被解析出来而不是把一份可用文档变成 404。资产存放在自己的表里，因为启动图重组会整体替换 bundle 响应表；它们的生命周期属于登记方的 effect。

**PDF.js 的 CMap、标准字体与 wasm 解码器改为提供，不再内联。** 构建公告它们的**名字**并把字节复制到 `lib/pdfjs-assets/`；node 半侧读该目录并登记；浏览器半侧只在某个文档请求时才取其中一个。`PdfBinaryDataFactory.fetch()` 本来就返回 `Promise<Uint8Array>`，因此没有调用方需要改动。

把名字清单留在 bundle 里，正是保住原有拒绝语义的原因：公告值是数组，因此穿越路径、未知文件、原型链成员都只是不在其中，会在任何请求离开页面之前被拒绝。node 半侧独立地只提供自己目录列表里有的东西，因此两侧都不依赖对方已经校验过。

node 半侧读的是本包，而不是在运行时解析 `pdfjs-dist`。已安装的布局可能把该依赖扁平化、提升或硬链接到任何位置，而 `pdfjs-dist` 保持为 `devDependencies` 里的构建输入。`../lib/pdfjs-assets/` 从源码启动的 `src/index.ts` 与构建产物的 `lib/index.js` 解析结果相同，因为两者都在包根下一层。

这推翻了原先「不带网络回退地捕获本次构建的二进制资产」这条规则，范围限于这三类资源。现在打开 PDF 依赖同源请求——Web 上是 HTTP，Electron 下是 `dsh-app://`，都不出本机。取不到的资源会让文档加载失败，而不是用替代字形或跳过图像把它渲染出来。

## Alternatives considered

**只设体积上限，不给 documentpreview 瘦身。** 它那个 6.57 MB 的批次不可分割，且实测在阈值之上，页面仍然失败。

**让 documentpreview 自己开一条资产路由。** Electron 禁用 `webserver` 且复用同一份插件名册，那样 PDF 渲染会在那里坏掉。

**把 PDF 能力拆成懒加载包。** 做不到：`compose()` 把每个非 bootstrap row 都分配给 application 批次并全部预加载，模块系统没有按需批次。

**用比 base64 更紧凑的方式内联字节。** JS 字符串字面量必须把不可打印字节转义成 `\xNN`，每个占四字符，比 base64 的 33% 更差。

**只移出最大的那一类（wasm，2.03 MB）。** 剩下 4.86 MB，仍在实测的失败区间内。

**发送 `Content-Length` 以便检测截断响应。** 在这里无效。扩展是经 `eval` 重放的，网络层收到的是完整响应体，截断发生在它之上。

**把 worker 源码也移出去。** 它那 1.27 MB 仍然内联。运行时是用这份源码造 Blob 得到 Worker 的，而实测 2.16 MB 的结果已经通过，因此这项额外改动只带来风险，没有收益证据。

## Consequences

`documentpreview` 的客户端 bundle 从 6,888,196 字节降到 2,268,444 字节；最大启动批次从 12.6 MB 降到 2.16 MB；客户端总量从 12.6 MB 降到约 8 MB。每个部署在首屏之前少下载 4.6 MB，与暴露出这个问题的那个扩展无关。

发布的包携带 `lib/pdfjs-assets/**`（189 个文件，3,466,109 字节），经 `packageFileExtras` 声明。发布字节净减少，因为同一份数据不再以 base64 形式存在 `client.js` 里。License 不变：PDF.js 仍随本包分发，bundle banner 仍携带全部十份声明。

启动的请求数增加（约八个 application 批次，而非一个）。它们并行预加载且每个都小得多，因此单次失败的代价从整个页面变成一个批次。

那条误导性的诊断信息仍然存在。批次执行完却没有注册时，`arrive()` 依旧报「loaded without registering」，真正的 `SyntaxError` 依旧只出现在 console 里。改进这条信息被推迟，不属于本 note。

## Verification

`packages/client/modules` 覆盖了经两个载体的资产登记与取回、查询键被忽略、跨 `compose()` 重组后仍存活、重复路径被拒绝并回滚部分登记、以及释放。`packages/client/ui-sidebar-documentpreview` 覆盖了 node 半侧以正确 content type 登记真实资源并排除 license，以及浏览器半侧的 URL 构造、每次调用的 buffer 独立性、拒绝未公告名字且不发请求、非 2xx 失败。`test:gui`、`typecheck`、`lint`、`hygiene` 均通过。

本地未验证：`test:web`（浏览器 e2e 与 web 快照）与 Electron 载体路径。开发机上装不上 Playwright 的 chromium-headless-shell（`browserType.launch: Executable doesn't exist`，且其下载失败），因此这两项信号归 CI。夹定阈值的那次二分法是由使用者对着实际隧道与真实扩展跑出来的，不是自动化套件的结果。
