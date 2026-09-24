# Agent Note: Subprocess spill recreate-retry retired

Status: implemented

English | [中文](2026-09-24-subprocess-spill-recreate-retry-retired.zh.md)

## Problem

This fork carried its own spill-fault containment in `dsh-subprocess-local` ([the containment decision](../bug-fix/2026-09-15-subprocess-spill-fault-degradation.md)): `OutputCollector` recreated its private spill directory with `mkdirSync` (recursive, `0o700`) and retried the exclusive open once, so a host whose temp directory had been swept by external cleanup kept recovering complete streams. Upstream then reached the same containment goal along a different path — `SpillOptions.onFailure`, one `error` line through the owner's logger from `logSpillFailure`, a `spillDisabled` flag that closes spilling for the collector's remaining lifetime, and publication of the spill path only after a successful open so a planted entry is never unlinked. Keeping the recreate-retry on top of that would mean re-porting a local branch into `output.ts` — an upstream file that changes frequently — at every future merge, and owning the interaction between recreating the directory and upstream's permanent-disable flag.

## Decision

The recreate-retry is retired; `dsh-subprocess-local` is taken from upstream whole. A spill open or write fault now discards the incomplete spill, reports once through `SpillOptions.onFailure`, sets `spillDisabled`, and leaves the stream with its in-memory tail alone for the rest of that collector's life.

The containment decision the earlier note records is unchanged and still shipped: spill I/O runs inside a stream `'data'` listener, so it must never throw. Upstream owns the realization, and its containment is wider than this fork's was; [that note](../bug-fix/2026-09-15-subprocess-spill-fault-degradation.md) carries the current mechanism.

This reverses one rationale in that note, which rejected "swallow every spill error with a persistent in-memory flag and no retry" on the grounds that temp-directory cleanup is a recurring event on long-lived hosts and the directory is cheap to recreate. That reasoning still describes a real loss; it is outweighed by upstream owning the file.

## Alternatives considered

**Port the recreate-retry onto upstream's structure and add a matching spec.** Rejected: `output.ts` is an upstream file under active change, and this would add a permanent per-merge porting cost plus a semantic interaction to maintain (recreating the directory after `spillDisabled` is already set has no effect, so the retry would have to run before upstream's own catch). The gain is one class of temp-directory fault, and only for the completeness of a recovery artifact.

**Archive the earlier note and record everything here.** Rejected: its containment decision is still the shipped contract and upstream shipped no note of its own, so archiving would leave that rationale carried only by a code comment and the package README.

**Rewrite the earlier note's rejected-alternatives reasoning to match what shipped.** Rejected: `implemented/` notes may have facts corrected but not their rationale rewritten, and that rejected alternative is exactly the reasoning a future reader needs when spilling stops working on a swept host. Its reasoning therefore stays verbatim, with one clause stating that the shipped code no longer matches it and pointing here.

## Consequences

On a host whose per-process spill directory is removed by an external temporary-file cleaner, the affected collector emits one `error` log line and then keeps only in-memory tails for the rest of the process. Full-stream recovery for those streams is gone until restart, where this fork previously recovered it silently. Reads stay available and the host keeps serving, which is what the containment decision protects.

`OutputCollector`'s signature is upstream's `(maxBytes, label, spill?: SpillOptions)`; the fork's `(maxBytes, maxSpillBytes, label, spillDir)` form and the `newSpillFile` / `openSpillFile` helpers no longer exist. `packages/subprocess/subprocess-local` now has no local modification, so it needs no merge-time protection.

## Verification

Retirement leaves no fork-owned behavior to cover; upstream's fault-injection cases are listed in [the containment note](../bug-fix/2026-09-15-subprocess-spill-fault-degradation.md). `packages/subprocess/subprocess-local` matches the upstream tag exactly, so what this change needed was evidence that nothing else depends on the removed signature: `pnpm run typecheck` and `pnpm run build` both pass on this fork. `tests/spawn.spec.ts` stays excluded on win32 by the package `vitest.config.ts`, so its behavioral evidence still comes from CI or a POSIX host — now as upstream's obligation rather than this fork's.
