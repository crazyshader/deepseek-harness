/**
 * Host half: serves the PDF.js binary resources the browser half fetches on
 * demand. They stay out of the client bundle because they are large enough that
 * one truncated transfer of the combined script costs the whole page, and they
 * are needed only when a PDF is actually opened.
 */
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Context } from '@deepseek-ai/cordis'
import type { ClientAssetResponse } from '@deepseek-ai/dsh-client-modules'
import {
  PDF_ASSET_DIRECTORIES, PDF_ASSET_KINDS, PDF_ASSET_OUTPUT_DIR, PDF_ASSET_PACKAGE, pdfAssetPath,
} from './pdf-asset-route.ts'

/** Content types for the resource kinds PDF.js requests; everything else is opaque bytes. */
const ASSET_CONTENT_TYPES: Record<string, string> = { '.wasm': 'application/wasm' }
const DEFAULT_ASSET_CONTENT_TYPE = 'application/octet-stream'

/**
 * Resource root inside this package. `../` reaches the package root from either
 * entry — this module runs as `src/index.ts` under a source launch and as
 * `lib/index.js` from the built artifact, and both sit one level below it.
 */
const ASSET_ROOT = fileURLToPath(new URL(`../${PDF_ASSET_OUTPUT_DIR}/`, import.meta.url))

/**
 * Read every resource the build copied into this package. The directory listing
 * is the whole white list: a name absent from it has no registered path and
 * answers 404, independently of the browser half's own check.
 * @returns asset path relative to the package's asset root, to its response.
 * @throws {Error} when the resources are missing, which means the package was
 * never built; a silent empty registration would instead surface as an
 * unexplained PDF failure much later.
 */
function readPdfAssets(): Map<string, ClientAssetResponse> {
  const assets = new Map<string, ClientAssetResponse>()
  for (const kind of PDF_ASSET_KINDS) {
    const directory = PDF_ASSET_DIRECTORIES[kind]
    let names: string[]
    try {
      names = readdirSync(join(ASSET_ROOT, directory)).sort()
    } catch (error) {
      throw new Error(
        `document preview: PDF.js resources are missing at ${join(ASSET_ROOT, directory)}; run \`pnpm run build\``,
        { cause: error },
      )
    }
    for (const filename of names) {
      const extension = filename.slice(filename.lastIndexOf('.'))
      assets.set(pdfAssetPath(kind, filename), {
        body: readFileSync(join(ASSET_ROOT, directory, filename)),
        contentType: ASSET_CONTENT_TYPES[extension] ?? DEFAULT_ASSET_CONTENT_TYPE,
      })
    }
  }
  return assets
}

export const inject = ['clientModules']

/**
 * Host plugin body: publish the PDF.js resources through the shared `/plugins`
 * carrier, which every deployment already answers — the Web prefix route and the
 * shell's `fetchBundle` alike.
 * @param ctx - plugin context carrying the client module registry.
 */
export function apply(ctx: Context): void {
  ctx.effect(
    () => ctx.clientModules.registerAssets(PDF_ASSET_PACKAGE, readPdfAssets()),
    'document preview: pdfjs assets',
  )
}
