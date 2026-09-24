# Agent Note: Subprocess spill-fault degradation

Status: implemented

English | [中文](2026-09-15-subprocess-spill-fault-degradation.zh.md)

## Problem

A long-running host (observed with `dsh web`) crashed with an uncaught `ENOENT` from `openSync` inside the stderr collector's stream callback. The per-process private spill directory, created once at first spawn, had been removed from the OS temp dir by external cleanup while the process was alive; the next overflow of a collected stream then tried to open its spill file in the missing directory. The throw escaped the stream `data` event, became an uncaught exception, and killed the whole host process — a best-effort output-recovery failure with host-wide blast radius.

## Decision

In `dsh-subprocess-local`, creating and writing a spill file can no longer throw out of the stream callback. `OutputCollector.spillAll` contains every filesystem fault it can raise — the exclusive open of the random-named file, the one-time backfill of already-collected chunks, and each per-chunk `writeSync`: the collector discards the incomplete spill, stops advertising a `spillPath`, and reports the error once through `SpillOptions.onFailure`, mirroring the existing containment rule for a failed final close in `seal`. Discarding also sets `spillDisabled`, so one fault ends spilling for the rest of that collector's life and produces exactly one report instead of one per subsequent chunk; that stream keeps only its in-memory tail. The private spill directory is created once per process and never recreated, so a directory an external temp-file cleaner removed takes every later collector in that process down the same path until it restarts, while a per-file fault such as `ENOSPC` or `EEXIST` costs only the stream that hit it. The spill path is recorded only after the open succeeds, so discarding never unlinks a path this process did not create, and a reporter that throws is caught and written to stderr rather than becoming the uncaught exception this path exists to prevent. The tail-keep memory buffer is always retained, so output reads stay available and the host process keeps serving.

## Alternatives considered

**Swallow every spill error with a persistent in-memory flag and no retry.** Rejected here: external temp-dir cleanup is a recurring, expected event on long-lived hosts, and the directory is cheap and safe to recreate; permanent degradation of full-output recovery after a single transient fault is unnecessary loss. This reasoning does not match the shipped code, which uses exactly that persistent flag: the fork's recreate-retry is retired and upstream owns the containment ([why](../simplification/2026-09-24-subprocess-spill-recreate-retry-retired.md)).

**A global `process.on('uncaughtException')` handler in the host.** Rejected: it would mask every other synchronous throw in any callback and hide real bugs; the crash path this fix closes is the only spill I/O that runs uncontained inside a stream callback.

## Consequences

A stream whose spill file cannot be created or written still settles with its truncated in-memory tail and no `spillPath`, exactly like a failed final close. `readFrom` on such a stream is simply not lossy-recoverable from a spill file. Completed spill files remain untouched, and the owner-only `0o700` directory with `0o600` random-named files keeps the symlink-planting and path-prediction defenses of the shared temp dir. Hosts whose temp dir is genuinely unwritable now lose full-stream recovery for that stream instead of the entire process.

## Verification

The `node:fs` fault-injection mock in [the spawn spec](../../../../packages/subprocess/subprocess-local/tests/spawn.spec.ts) carries `failNextOpen` and `failNextWrite` switches. The specs cover a removed spill directory (`ENOENT`), a directory path that is a file (`ENOTDIR`), an append failure after the file exists (`ENOSPC`), a failed exclusive open that must not unlink (`EEXIST`), a reporter that throws, and a bare `spawnSubprocess` with no owner logger. `tests/spawn.spec.ts` is excluded on win32 by the package `vitest.config.ts`, so behavioral evidence comes from CI or a POSIX host.

The crash this closes was reproduced in a `dsh web` host on Windows: the crashed run's `dsh-subprocess-*` directory was gone from the temp dir while the sibling per-process directories survived, confirming the external-removal trigger.
