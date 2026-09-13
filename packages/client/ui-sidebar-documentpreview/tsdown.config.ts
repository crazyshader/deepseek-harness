import { copyFileSync, mkdirSync, readFileSync, readdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import type { UserConfig } from 'tsdown'
import { clientBundle } from '../tsdown.client.ts'
import { PDF_ASSET_DIRECTORIES, PDF_ASSET_KINDS, PDF_ASSET_OUTPUT_DIR } from './src/pdf-asset-route.ts'

const bundle = clientBundle('@deepseek-ai/dsh-client-ui-sidebar-documentpreview', ['lib/types/index.js'])
const require = createRequire(import.meta.url)
const workerSpecifier = 'pdfjs-dist/build/pdf.worker.min.mjs?raw'
const workerModule = '\0dsh-pdf-worker.mjs'

/** License files for PDF.js and the data served beside its runtime. */
function pdfLicenseFiles(root: string): string[] {
  return ['LICENSE', ...['cmaps', 'standard_fonts', 'wasm'].flatMap(directory =>
    readdirSync(join(root, directory)).filter(name => name.startsWith('LICENSE')).sort()
      .map(name => `${directory}/${name}`),
  )]
}

/** Keep every PDF.js license this package distributes visible in the published client artifact. */
function pdfLicenseBanner(): string {
  const root = dirname(require.resolve('pdfjs-dist/package.json'))
  const notice = pdfLicenseFiles(root).map(name =>
    `${name}\n\n${readFileSync(join(root, name), 'utf8').trimEnd()}`,
  ).join('\n\n')
  return ['//! Bundled PDF.js license notices', ...notice.split('\n').map(line => `// ${line}`)].join('\n')
}

/**
 * Advertise the binary resource names, not their bytes. The host serves the data
 * beside this bundle; the browser keeps only the list, which is what lets it
 * refuse an unadvertised or traversing filename without a request.
 */
function pdfAssetManifest(root: string): string {
  return JSON.stringify(Object.fromEntries(PDF_ASSET_KINDS.map(kind => [
    kind,
    readdirSync(join(root, PDF_ASSET_DIRECTORIES[kind])).filter(name => !name.startsWith('LICENSE')).sort(),
  ])))
}

/**
 * Copy the binary resources into this package, where the host half reads them.
 * They travel with the published package instead of being resolved out of
 * `pdfjs-dist` at runtime, so no installed dependency layout can hide them.
 */
const pdfAssetCopy: NonNullable<UserConfig['plugins']> = [{
  name: 'dsh-pdf-asset-copy',
  writeBundle(): void {
    const root = dirname(require.resolve('pdfjs-dist/package.json'))
    for (const kind of PDF_ASSET_KINDS) {
      const directory = PDF_ASSET_DIRECTORIES[kind]
      const target = join(import.meta.dirname, PDF_ASSET_OUTPUT_DIR, directory)
      mkdirSync(target, { recursive: true })
      for (const name of readdirSync(join(root, directory))) {
        // Licenses are disclosed in the bundle banner, not served as assets.
        if (name.startsWith('LICENSE')) continue
        copyFileSync(join(root, directory, name), join(target, name))
      }
    }
  },
}]

/** The dynamic client factory has no module URL from which to resolve a Worker file. */
const pdfWorker: NonNullable<UserConfig['plugins']> = [{
  name: 'dsh-pdf-worker-source',
  resolveId(source) {
    return source === workerSpecifier ? workerModule : null
  },
  load(id) {
    if (id !== workerModule) return null
    const path = require.resolve('pdfjs-dist/build/pdf.worker.min.mjs')
    this.addWatchFile(path)
    return `export default ${JSON.stringify(readFileSync(path, 'utf8'))};`
  },
}]

export default (options: Parameters<typeof bundle>[0]): UserConfig[] => {
  const root = dirname(require.resolve('pdfjs-dist/package.json'))
  const version = (JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')) as { version: string }).version
  return bundle(options).map(config =>
    config.name?.endsWith('/client') === true ? {
      ...config,
      banner: pdfLicenseBanner(),
      plugins: [config.plugins, pdfWorker, pdfAssetCopy],
      define: {
        ...config.define,
        __DSH_PDFJS_ASSETS__: pdfAssetManifest(root),
        __DSH_PDFJS_VERSION__: JSON.stringify(version),
      },
    } : config,
  )
}
