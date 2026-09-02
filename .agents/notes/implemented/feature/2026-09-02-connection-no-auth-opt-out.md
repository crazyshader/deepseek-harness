# Agent Note: Connection no-auth opt-out

Status: implemented

English | [中文](2026-09-02-connection-no-auth-opt-out.zh.md)

## Problem

The browser connection authenticates every launch with a host-bound one-time token and a `SameSite=None` session cookie; `RpcHost` rejects any request that carries neither. That is right for a cross-origin browser a script can reach, but it also blocks the local case of a process that owns the listening socket and is not such a browser — the `dsh-launcher` desktop shell, a local automation run, a test — which must run the full launch-token exchange just to reach the server it started. There is no way to admit the loopback and declared authorities without credentials without weakening that token for every other deployment.

## Decision

`packages/client/connection` resolves the browser-auth service through a `BrowserAuthenticator` interface — `isAuthenticated`, `authorizeIndex`, `authenticatedUrl` — instead of the concrete `BrowserAuth`. `BrowserAuth` implements it unchanged; a second value, `NO_AUTH_BROWSER_AUTH`, implements it as a no-op (`isAuthenticated` and `authorizeIndex` return `true`, `authenticatedUrl` returns its input). `apply` selects the value from the new `noAuth` config field: `config?.noAuth === true ? NO_AUTH_BROWSER_AUTH : await BrowserAuth.create(...)`. `RpcHost`'s constructor takes `BrowserAuthenticator`, so it holds the chosen value with no per-request branch.

The flag reaches two places. `dsh web` adds `--no-auth` (a commander `auth` option, default on) and puts `noAuth: !options.auth` in the web-startup service; the connection plugin's `cordis.patch.yml` reads `!!js ctx.webStartup.noAuth` into `config.noAuth`. `dsh-launcher` adds a "免 token 认证" checkbox that appends `--no-auth` to the `dsh web` command it spawns, and `config.py` defaults `no_auth` to `False` so the box is off unless the operator ticks it.

The opt-out changes only credentialing. The authority check is separate: `RpcHost.requestRejection` still runs the `trustedHosts` check and answers `403` to an undeclared non-loopback authority, and the web server still binds loopback-only and rejects `--host 0.0.0.0`. `--no-auth` therefore admits the declared authorities without a token or cookie; it does not widen which hosts are admitted.

## Alternatives considered

**A `noAuth` branch inside `BrowserAuth`.** Keeps one class, but threads a mode flag through every method and makes the token path and the no-auth path know about each other; the interface value keeps the no-op out of the real class and gives `RpcHost` a plain value to hold.

**Thread `noAuth` into `RpcHost` and skip the service call there.** Couples the host to the config flag and duplicates the "is this request admitted?" decision the interface already centralizes; holding the value at construction leaves the request path branch-free.

**Default the launcher on (`no_auth: True`).** Convenient for the desktop case, but a GUI default that silently turns off a security control on every launch is a footgun; the CLI default is auth-on and the GUI now matches it, with the checkbox as the explicit opt-in.

## Consequences

- With `--no-auth`, a loopback or declared-authority client reaches the web server with no token or cookie: the index serves and `/api` bridges without the launch-token exchange.
- The authority fence is unchanged — an undeclared non-loopback `Host` still gets `403` and the server still refuses `0.0.0.0` — so the flag removes credentials, not reachability.
- `src/browser-auth.ts` must keep `NO_AUTH_BROWSER_AUTH` covered (its three no-op methods are exercised by `tests/browser-auth.host.spec.ts`); `src/index.ts` and `http-bridge.ts` stay in the coverage exclusion list under the client-lane TODO.
- `dsh-launcher` build outputs are git-ignored by a new `dsh-launcher/.gitignore`; the PyInstaller intermediates under `build/` are no longer tracked.
