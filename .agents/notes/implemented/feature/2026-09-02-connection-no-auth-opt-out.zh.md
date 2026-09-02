# Agent Note: Connection no-auth opt-out

Status: implemented

[English](2026-09-02-connection-no-auth-opt-out.md) | 中文

## Problem

浏览器连接用「host 绑定的一次性 token + `SameSite=None` 会话 cookie」为每次启动做认证；`RpcHost` 会拒绝两者都不携带的请求。对一个脚本能触达的跨源浏览器，这是对的；但它也挡住了本地场景里「拥有监听 socket 且不是这类浏览器的进程」——`dsh-launcher` 桌面外壳、本地自动化运行、测试——它们必须完整走一遍 launch-token 交换，才能够到自己启动的服务器。要在不凭据的情况下放行 loopback 与已声明 authority，又不削弱其他部署的这个 token，目前没有途径。

## Decision

`packages/client/connection` 通过 `BrowserAuthenticator` 接口——`isAuthenticated`、`authorizeIndex`、`authenticatedUrl`——解析浏览器认证服务，而不是直接用具体类 `BrowserAuth`。`BrowserAuth` 原样实现该接口；第二个取值 `NO_AUTH_BROWSER_AUTH` 把它实现为 no-op（`isAuthenticated` 与 `authorizeIndex` 返回 `true`，`authenticatedUrl` 原样返回入参）。`apply` 依据新的 `noAuth` 配置字段选值：`config?.noAuth === true ? NO_AUTH_BROWSER_AUTH : await BrowserAuth.create(...)`。`RpcHost` 的构造参数是 `BrowserAuthenticator`，于是不带任何按请求的分支就持有选中的取值。

这个 flag 到达两处。`dsh web` 增加 `--no-auth`（commander 的 `auth` 选项，默认开），并在 web-startup service 里放入 `noAuth: !options.auth`；connection 插件的 `cordis.patch.yml` 读 `!!js ctx.webStartup.noAuth` 到 `config.noAuth`。`dsh-launcher` 增加一个「免 token 认证」复选框，在它 spawn 的 `dsh web` 命令后追加 `--no-auth`；`config.py` 把 `no_auth` 默认设为 `False`，所以复选框默认不勾选、除非操作者勾上。

opt-out 只改动凭据校验。authority 检查是独立的：`RpcHost.requestRejection` 仍跑 `trustedHosts` 检查、对未声明的非 loopback authority 返回 `403`，web server 仍只绑 loopback、拒绝 `--host 0.0.0.0`。因此 `--no-auth` 让已声明 authority 免 token/cookie 通过，并不扩大被放行的 host 范围。

## Alternatives considered

**在 `BrowserAuth` 内部加 `noAuth` 分支。** 保持单类，但把模式 flag 穿进每个方法、让 token 路径与 no-auth 路径互相知道；接口取值把 no-op 隔离在真实类之外，并让 `RpcHost` 持有一个普通取值。

**把 `noAuth` 穿进 `RpcHost`、在那跳过 service 调用。** 把 host 耦合到配置 flag、并重复了接口已集中化的「这个请求是否放行」判断；在构造时持有取值可让请求路径无分支。

**launcher 默认开（`no_auth: True`）。** 对桌面场景方便，但一个 GUI 默认值在每次启动时悄悄关掉安全控制是个 footgun；CLI 默认是认证开，GUI 现与之对齐，复选框作为显式 opt-in。

## Consequences

- 设置 `--no-auth` 后，loopback 或已声明 authority 的客户端免 token/cookie 到达 web server：index 直接服务、`/api` 不经 launch-token 交换即桥接。
- authority fence 不变——未声明的非 loopback `Host` 仍得 `403`、服务器仍拒绝 `0.0.0.0`——所以该 flag 去掉的是凭据，不是可达性。
- `src/browser-auth.ts` 必须保持 `NO_AUTH_BROWSER_AUTH` 被覆盖（其三个 no-op 方法由 `tests/browser-auth.host.spec.ts` 行使）；`src/index.ts` 与 `http-bridge.ts` 仍留在 coverage 排除列表下（client-lane TODO）。
- `dsh-launcher` 的构建产物由新增的 `dsh-launcher/.gitignore` 忽略；`build/` 下的 PyInstaller 中间产物不再被跟踪。
