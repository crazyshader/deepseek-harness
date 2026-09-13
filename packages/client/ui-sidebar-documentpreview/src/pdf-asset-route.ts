/**
 * The PDF.js asset address, shared by both halves of this package: the node half
 * registers these paths with `clientModules`, and the browser half builds the
 * same URLs to fetch them. One module owns the mapping so the two sides cannot
 * drift apart.
 */

/** Resource kinds used by PDF.js 6's BinaryDataFactory requests. */
export type PdfAssetKind = 'cMapUrl' | 'standardFontDataUrl' | 'wasmUrl'

/** This package's name, which is also the asset route's owner segment. */
export const PDF_ASSET_PACKAGE = '@deepseek-ai/dsh-client-ui-sidebar-documentpreview'

/**
 * Package-relative directory the build copies the resources into, so the host
 * half reads them out of this package rather than resolving `pdfjs-dist` at
 * runtime — an installed layout may flatten, hoist, or hard-link that
 * dependency anywhere.
 */
export const PDF_ASSET_OUTPUT_DIR = 'lib/pdfjs-assets'

/** Directory inside `pdfjs-dist` that supplies each request kind. */
export const PDF_ASSET_DIRECTORIES = {
  cMapUrl: 'cmaps',
  standardFontDataUrl: 'standard_fonts',
  wasmUrl: 'wasm',
} as const satisfies Record<PdfAssetKind, string>

/** Every request kind, for iterating both halves' asset tables in one order. */
export const PDF_ASSET_KINDS = Object.keys(PDF_ASSET_DIRECTORIES) as readonly PdfAssetKind[]

/**
 * Asset path relative to the package's asset root.
 * @param kind - PDF.js resource kind.
 * @param filename - exact filename inside that kind's directory.
 * @returns the path the node half registers.
 */
export function pdfAssetPath(kind: PdfAssetKind, filename: string): string {
  return `${PDF_ASSET_DIRECTORIES[kind]}/${filename}`
}

/**
 * Absolute URL the browser fetches one asset from. The version is a cache key
 * only: the host matches on pathname, so a key from a different `pdfjs-dist`
 * version still resolves rather than 404ing a working document.
 * @param kind - PDF.js resource kind.
 * @param filename - exact filename inside that kind's directory.
 * @param version - `pdfjs-dist` version recorded at build time.
 * @returns the same-origin URL served by whichever carrier answers `/plugins`.
 */
export function pdfAssetUrl(kind: PdfAssetKind, filename: string, version: string): string {
  const path = `${PDF_ASSET_DIRECTORIES[kind]}/${encodeURIComponent(filename)}`
  return `/plugins/${PDF_ASSET_PACKAGE}/assets/${path}?v=${encodeURIComponent(version)}`
}
