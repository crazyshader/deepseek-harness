# Agent Note: Startup batch bodies are bounded by served bytes

Status: implemented

English | [中文](2026-09-18-combo-body-size-limit.zh.md)

## Problem

A combo batch is one `<script>` holding many plugin factories concatenated with `;`. That makes it all-or-nothing: the first incomplete statement stops every later `__ModuleLoader__.load` in the same file, and the browser still fires `load` because an uncaught exception does not fail script loading. The module system then reports the least informative fact available to it — some row was not registered — while the real error stays in the console.

Batch partitioning bounded only the request URL (3 KiB), never the served body. One deployment therefore served all application rows as a single 12.6 MB script. A browser extension that intercepted the script, refetched it, and replayed it through `eval` truncated the content at 99.11%, and the whole page failed to boot with a message that pointed at the wrong subsystem. Measured by bisection against that live deployment, every batch at or below about 1 MiB arrived intact.

## Decision

**Batches are bounded by served bytes as well as by URL length.** `MAX_COMBO_BODY_BYTES` is 1 MiB. The two limits differ in whether they yield: an unaddressable URL fails composition, while a bundle larger than the body limit is still addressable and forms its own batch rather than failing. Graph order is preserved, so a batch boundary never places a requested module after its consumer.

The limit measures the artifact bytes a batch would serve, before combo framing and gzip. That undercounts the framing overhead slightly and is deliberately not exact: the threshold it defends is empirical, and a batch already near 1 MiB is far from the failure range whichever way the framing rounds.

## Alternatives considered

**Bound nothing and rely on `Content-Length` to detect truncation.** Ineffective against the observed failure. The extension replays through `eval`, so the network layer received the complete body; the truncation happened above it.

**Make an oversized single bundle fail composition, like an oversized URL.** A bundle above the body limit is still individually addressable and serviceable, so failing would take away a working capability to enforce a bound that cannot help in that case. It forms its own batch instead.

**Improve the diagnostic instead of the partitioning.** The misleading message is real but orthogonal: `arrive()` still reports "loaded without registering" when a batch executes without registering, and the actual `SyntaxError` still appears only in the console. Improving that message is deferred and not part of this note.

## Consequences

Startup makes more requests than one combined script would. They are preloaded in parallel and each is far smaller, so a single failure costs one batch rather than the page.

This note supersedes the asset-route half of [the PDF.js asset decision](../../archived/architecture/2026-09-12-pdfjs-assets-out-of-bundle.md), which is archived. `clientModules.registerAssets()` and the `/plugins/<id>/assets/<path>` route are gone: `ui-sidebar-documentpreview` now loads PDF.js in an on-demand package-local chunk that carries its own binary data, so those resources never enter a startup batch and no longer need a separate carrier. The body limit stands on its own, independent of any single package's size.

## Verification

`packages/client/modules/tests/node-half.client.spec.ts` covers both partitioning outcomes: three artifacts split before the served body crosses 1 MiB, and a single oversized bundle taking its own batch without failing composition. The 1 MiB threshold itself came from bisection against a live tunnel and a real browser extension, run by the user; no automated suite reproduces that transport.
