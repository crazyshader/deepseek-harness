# dsh-launcher

English | [中文](README.zh.md)

The graphical launcher for DeepSeek Harness. The main window has two tabs: "Control" offers install, build, launch, and stop with live log output from the underlying commands; "Plugins" installs and uninstalls third-party plugins for the web profile, and provides recovery when a plugin compatibility issue prevents DSH from starting. Features align with the project-root `quick-start.bat`; implemented with PySide6 and packable to a standalone exe via PyInstaller.

## Features

### Control tab

| Button | Command run |
|------|-----------|
| Install | `pnpm install` |
| Build | `pnpm run clean` then `pnpm run build` (two steps; any failure aborts) |
| Launch | `pnpm dsh web --port <port>` (resident web service) |
| Stop | kills the whole process tree (`taskkill /T /F`), freeing the port |

Other behaviors:

- **Project directory**: must be chosen on first run (the DeepSeek Harness project root), then remembered (config at `%APPDATA%\dsh-launcher\config.json`).
- **Port**: configurable, default 3080, persisted together with the config.
- **Open Web after launch**: when checked, opens `http://localhost:<port>` once the service is ready.
- **Idempotent launch**: probes the target port before launching; if it is in use (from any source), cleans up the occupying process first to avoid a port-conflict launch failure.
- **Single-task mutual exclusion**: only one task runs at a time; while one is running, the other action buttons are disabled (the Plugin tab buttons are subject to the same constraint).
- **Soft pre-checks**: warns (rather than hard-locking the buttons) when `node_modules` is missing or the web front-end is unbuilt.
- **Closing the window**: if a service is still running, asks whether to stop it before exiting.
- **Secrets**: does not handle `DEEPSEEK_API_KEY`; it inherits the project-root `.env`. If unset, dsh itself reports the error in the log.

### Plugin tab

The managed target is fixed to the `web` profile (`$DSH_HOME/profiles/web`, `DSH_HOME` defaulting to `~/.dsh`). Plugin install/uninstall goes through the official mechanism `dsh plugin --profile web add|remove <spec>` (forwards pnpm and maintains the `dsh.profile.bundles` layer list); the user-owned `cordis.patch.yml` (such as MCP servers) is unaffected.

**Install**

- The input box accepts any pnpm dependency spec: an npm package name (optionally versioned), `github:owner/repo` (optionally with `#commit`), a local `.tgz` package, or a local directory.
- The "Directory…" and "Package…" buttons pick a local plugin source directory or archive and fill in the absolute path; picking a directory installs with link semantics (source changes take effect on restart).
- Before every install through the launcher, a **pre-install snapshot** is taken automatically (below); the log records the snapshot name.
- If a first install from a git source fails on pnpm build authorization (`allowBuilds`), dsh prints the fix in the log; after editing the profile's `pnpm-workspace.yaml` as instructed, click install again. The launcher does not perform this authorization automatically.

**Uninstall**

- The list shows the installed third-party plugins (the built-in `dsh-base`/`dsh-web-app` cannot be uninstalled).
- "Uninstall selected" only uninstalls without restarting; "Uninstall selected and retry" and "Uninstall latest and retry" restart the web service after uninstalling (stop the current service first, then run the recovery chain).
- Uninstall takes no snapshot; after an accidental uninstall, reinstall with the install button (version re-resolved by package name).

**Pre-install snapshots and rollback (fault recovery)**

- Snapshot contents: the profile directory's `package.json`, `pnpm-lock.yaml`, and `pnpm-workspace.yaml`, stored at `$DSH_HOME/profiles/.dsh-plugin-snapshots/web/<时间戳>/` (outside the profile directory), each annotated with "which plugin was being installed"; at most the 5 most recent are kept, and older ones are deleted. `node_modules` is not copied (rebuilt with `pnpm install` after restore).
- When a plugin compatibility issue prevents DSH from starting and the web will not open, run the recovery action manually in the Plugin tab (the launcher does not auto-detect failure; the user decides):
  1. **Uninstall latest and retry** — restart after uninstalling the most recently installed third-party plugin;
  2. **Roll back to latest/selected and retry** — restore the profile's manifest files to a snapshot's recorded state (files not recorded in the snapshot are deleted, returning fully to the pre-install state), then run `pnpm install` in the profile directory to rebuild dependencies, verify the config combination loads with `dsh --profile web --dump-config`, and finally restart the web service.
- Any failure in the recovery chain aborts the remaining steps (it never restarts in a broken state); the whole process is in the log.
- The rollback chain's `pnpm install` step needs the network (registry dependency); offline, it stops at that step.
- Even if the profile's `package.json` is corrupted to the point where `dsh plugin` cannot run, rollback still works — it only restores files and runs `pnpm install`, without depending on `dsh plugin`.

## Development run

```powershell
# 在 dsh-launcher 目录下
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## Package to exe

**Double-click `build.bat`**: it finds Python automatically (`python` or `py -3`), installs PyInstaller if missing, runs the packaging, opens the `dist` output directory on success, and leaves the window open at the end so the result can be viewed.

You can also run it manually:

```powershell
pip install pyinstaller
python build.py
```

The artifact is `dist/dsh-launcher.exe`; double-click to use, with no Python install needed on the target machine. If the old exe is still running, packaging fails (the artifact is locked); close it first.

## Dependencies

- Python 3.9+
- PySide6 (see `requirements.txt`)
- The target machine must have `pnpm` installed and on PATH (the launcher only calls it)

## Platform

Windows only: process-tree cleanup and port probing depend on `taskkill` / `netstat`.
