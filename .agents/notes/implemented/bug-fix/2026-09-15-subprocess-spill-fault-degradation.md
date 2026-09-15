# Agent Note: Subprocess spill-fault degradation

Status: implemented

English | [中文](2026-09-15-subprocess-spill-fault-degradation.zh.md)

## Problem

A long-running host (observed with `dsh web`) crashed with an uncaught `ENOENT` from `openSync` inside the stderr collector's stream callback. The per-process private spill directory, created once at first spawn, had been removed from the OS temp dir by external cleanup while the process was alive; the next overflow of a collected stream then tried to open its spill file in the missing directory. The throw escaped the stream `data` event, became an uncaught exception, and killed the whole host process — a best-effort output-recovery failure with host-wide blast radius.

## Decision

In `dsh-subprocess-local`, creating and writing a spill file can no longer throw out of the stream callback. `OutputCollector.openSpillFile` first tries to open the random-named file in the private directory; on any open fault it recreates the directory with `mkdirSync` (recursive, `0o700`) and retries once with a fresh random name. The directory is safe to recreate because it is random-named, process-private, and owner-only. A second open fault, a fault while backfilling the already-collected chunks, or a fault in any per-chunk `writeSync` degrades the stream to the in-memory tail only: the collector discards the incomplete spill and stops advertising a `spillPath`, mirroring the existing containment rule for a failed final close in `seal`. The tail-keep memory buffer is always retained, so output reads stay available and the host process keeps serving.

## Alternatives considered

**Delete and recreate the directory eagerly on every open fault, without a retry.** Rejected: after a successful recreate-retry the file is open, so an extra delete pass would risk removing a live file's directory mid-write and gains nothing.

**Swallow every spill error with a persistent in-memory flag and no retry.** Rejected: external temp-dir cleanup is a recurring, expected event on long-lived hosts, and the directory is cheap and safe to recreate; permanent degradation of full-output recovery after a single transient fault is unnecessary loss.

**A global `process.on('uncaughtException')` handler in the host.** Rejected: it would mask every other synchronous throw in any callback and hide real bugs; the crash path this fix closes is the only spill I/O that runs uncontained inside a stream callback.

## Consequences

A stream whose spill file cannot be created or written still settles with its truncated in-memory tail and no `spillPath`, exactly like a failed final close. `readFrom` on such a stream is simply not lossy-recoverable from a spill file. Completed spill files remain untouched. The recreated directory keeps the owner-only `0o700` mode, so the symlink-planting and path-prediction defenses of the shared temp dir are unchanged. Hosts whose temp dir is genuinely unwritable now lose full-stream recovery for that stream instead of the entire process.

## Verification

The `node:fs` fault-injection mock in [the spawn spec](../../../../packages/subprocess/subprocess-local/tests/spawn.spec.ts) gained `failNextOpen` and `failNextWrite` counters. The new specs cover: a spill directory removed before the first overflow is recreated and the complete stream is still recovered end to end through a real `spawnSubprocess`; two consecutive open faults degrade to the tail with no `spillPath`; a backfill write fault and a mid-stream write fault each degrade to the tail and stop advertising the path. The package suite (105 tests) passes on this host.

The crash this closes was reproduced in a `dsh web` host on Windows: the crashed run's `dsh-subprocess-*` directory was gone from the temp dir while the sibling per-process directories survived, confirming the external-removal trigger.
