/**
 * Build-advertised, same-version PDF.js resources. The build inlines the worker
 * source and the *names* of every binary asset; the bytes themselves are served
 * by the host beside this package's bundle and fetched when a PDF needs them.
 * Keeping the name list in the bundle is what lets an unadvertised or traversing
 * filename be refused here, before any request leaves the page.
 */
import workerSource from 'pdfjs-dist/build/pdf.worker.min.mjs?raw'
import { pdfAssetUrl, type PdfAssetKind } from '../../pdf-asset-route.ts'

export { workerSource }
export type { PdfAssetKind }

/** Asset filenames this build advertises, per request kind. */
export type PdfAssetManifest = Readonly<Record<PdfAssetKind, readonly string[]>>

declare global {
  /** Advertised asset filenames supplied by the package-local build configuration. */
  const __DSH_PDFJS_ASSETS__: PdfAssetManifest
  /** `pdfjs-dist` version this bundle was built against, used as the asset cache key. */
  const __DSH_PDFJS_VERSION__: string
}

/** Public methods required by PDF.js's BinaryDataFactory option. */
export interface PdfBinaryDataFactory {
  /** @param request - PDF.js resource kind and exact filename. @returns independent transferable resource bytes. */
  fetch(request: { readonly kind: PdfAssetKind; readonly filename: string }): Promise<Uint8Array>
}

/**
 * Capture this build's advertised asset names, resolving bytes from the host on
 * demand. There is no fallback: an asset that cannot be fetched fails the
 * document rather than rendering it with substituted glyphs or skipped images.
 * @param manifest - build-advertised filenames, read only when a PDF is opened.
 * @param version - cache key for the asset URLs.
 * @returns the constructor passed to PDF.js getDocument.
 */
export function createPdfBinaryDataFactory(
  manifest: PdfAssetManifest = __DSH_PDFJS_ASSETS__,
  version: string = __DSH_PDFJS_VERSION__,
): new () => PdfBinaryDataFactory {
  return class implements PdfBinaryDataFactory {
    async fetch({ kind, filename }: { readonly kind: PdfAssetKind; readonly filename: string }): Promise<Uint8Array> {
      // The advertised list is an array, so a traversing path, an absent name,
      // and a prototype member are all simply absent from it.
      if (!manifest[kind].includes(filename)) {
        throw new Error(`PDF.js asset is not bundled: ${kind}/${filename}`)
      }
      const url = pdfAssetUrl(kind, filename, version)
      const response = await globalThis.fetch(url)
      if (!response.ok) {
        throw new Error(`PDF.js asset request failed: ${kind}/${filename} answered ${String(response.status)}`)
      }
      // A fresh ArrayBuffer per call: PDF.js may transfer the buffer to its worker.
      return new Uint8Array(await response.arrayBuffer())
    }
  }
}
