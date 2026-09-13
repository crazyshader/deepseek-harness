# Agent Note: Batch bodies are bounded, and PDF.js resources leave the bundle

Status: implemented

English | [中文](2026-09-12-pdfjs-assets-out-of-bundle.zh.md)

## Problem

A combo batch is one `<script>` holding many plugin factories concatenated with `;`. That makes it all-or-nothing: the first incomplete statement stops every later `__ModuleLoader__.load` in the same file, and the browser still fires `load` because an uncaught exception does not fail script loading. The module system then reports the least informative fact available to it — some row was not registered — while the real error stays in the console.

Batch partitioning bounded only the request URL (3 KiB), never the served body. One deployment therefore served all 59 application rows as a single 12.6 MB script. A browser extension that intercepted the script, refetched it, and replayed it through `eval` truncated the content at 99.11%, and the whole page failed to boot with a message that pointed at the wrong subsystem.

Bounding the body was not sufficient by itself. `ui-sidebar-documentpreview` alone was 6,888,196 bytes and cannot be split: 85% of it was PDF.js binary data inlined as base64 and as a JS string, which is 47% of the entire 12.6 MB client. Measured by bisection, that single package still exceeded the truncation threshold while every batch at or below about 1 MiB arrived intact.

## Decision

**Batches are bounded by served bytes as well as by URL length.** `MAX_COMBO_BODY_BYTES` is 1 MiB. The two limits differ in whether they yield: an unaddressable URL fails composition, while a bundle larger than the body limit is still addressable and forms its own batch rather than failing. Graph order is preserved, so a batch boundary never places a requested module after its consumer.

**`clientModules` serves package-owned static assets.** `registerAssets(id, assets)` publishes bytes at `/plugins/<id>/assets/<path>` and returns the disposer for exactly the paths it added. This reuses the one carrier every deployment already answers: the Web prefix route and the shell's `fetchBundle`, which is how Electron serves `/plugins/` with `webserver` disabled. A package therefore keeps binary resources out of its JavaScript without owning a route, and without any per-carrier wiring.

Assets match on pathname alone. They are versioned by their owning dependency rather than by a content revision, so the version travels as a query key for cache separation only and a stale key resolves instead of 404ing a working document. Assets live in their own table because graph recomposition replaces the bundle response tables wholesale; their lifetime belongs to the registrant's effect.

**PDF.js CMaps, standard fonts, and wasm decoders are served, not inlined.** The build advertises their *names* and copies their bytes into `lib/pdfjs-assets/`; the host half reads that directory and registers it; the browser half fetches one only when a document asks for it. `PdfBinaryDataFactory.fetch()` already returned `Promise<Uint8Array>`, so no caller changed.

Keeping the name list in the bundle is what preserves the previous refusal semantics: the advertised value is an array, so a traversing path, an unknown file, and a prototype member are all simply absent from it and are refused before any request leaves the page. The host independently serves only what its own directory listing contains, so neither side depends on the other having checked.

The host reads this package rather than resolving `pdfjs-dist` at runtime. An installed layout may flatten, hoist, or hard-link that dependency anywhere, and `pdfjs-dist` stays a build input in `devDependencies`. `../lib/pdfjs-assets/` resolves identically from `src/index.ts` under a source launch and from `lib/index.js` in the built artifact, because both sit one level below the package root.

This overrides the previous "capture this build's binary assets without network fallbacks" rule for these three resource sets. Opening a PDF now depends on same-origin requests — HTTP on the Web, `dsh-app://` under Electron, neither leaving the machine. An asset that cannot be fetched fails the document instead of rendering it with substituted glyphs or skipped images.

## Alternatives considered

**Bound the body without shrinking documentpreview.** Its 6.57 MB batch is indivisible and measured above the threshold, so the page still failed.

**Give documentpreview its own asset route.** Electron disables `webserver` and reuses the same plugin roster, so PDF rendering would have broken there.

**Split PDF support into a lazily loaded package.** Not available: `compose()` assigns every non-bootstrap row to an application batch and preloads all of them; the module system has no on-demand batch.

**Inline the bytes more compactly than base64.** A JS string literal must escape non-printable bytes as `\xNN`, four characters each, which is worse than base64's 33%.

**Move only the largest set (wasm, 2.03 MB).** That leaves 4.86 MB, still inside the measured failure range.

**Send `Content-Length` so a truncated response is detected.** Ineffective here. The extension replays through `eval`, so the network layer received the complete body; the truncation happened above it.

**Move the worker source out too.** Its 1.27 MB stays inlined. The runtime builds its Worker from a Blob over that source, and the measured 2.16 MB result already passed, so the additional change carried risk without evidence of benefit.

## Consequences

`documentpreview`'s client bundle is 2,268,444 bytes instead of 6,888,196; the largest startup batch is 2.16 MB instead of 12.6 MB; the client total is about 8 MB instead of 12.6 MB. Every deployment loads 4.6 MB less before first paint, independent of the extension that surfaced this.

The published package carries `lib/pdfjs-assets/**` (189 files, 3,466,109 bytes), declared through `packageFileExtras`. Net published bytes fall, because the same data no longer sits base64-encoded inside `client.js`. Licenses are unchanged: PDF.js still distributes with this package, and the bundle banner still carries all ten notices.

Startup makes more requests (about eight application batches instead of one). They are preloaded in parallel and each is far smaller, so a single failure now costs one batch rather than the page.

The misleading diagnostic remains. `arrive()` still reports "loaded without registering" when a batch executes without registering, and the actual `SyntaxError` still appears only in the console. Improving that message is deferred and not part of this note.

## Verification

`packages/client/modules` covers asset registration and retrieval through both carriers, the query key being ignored, survival across `compose()` recomposition, duplicate-path rejection with rollback of the partial registration, and disposal. `packages/client/ui-sidebar-documentpreview` covers the host half registering the real resources with correct content types and excluding licenses, and the browser half's URL construction, per-call buffer independence, refusal of unadvertised names without a request, and non-2xx failure. `test:gui`, `typecheck`, `lint`, and `hygiene` pass.

Not verified locally: `test:web` (browser e2e and web snapshots) and the Electron carrier path. Playwright's chromium-headless-shell could not be installed on the development host (`browserType.launch: Executable doesn't exist`, and its download failed), so CI owns both signals. The bisection that fixed the threshold was run by the user against a live tunnel and a real extension, not by an automated suite.
