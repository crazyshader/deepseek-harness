/** PDF binary resources are exact-name, host-served data with independent transferable buffers. */
import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
import { createPdfBinaryDataFactory, type PdfAssetManifest } from '../src/client/pdf/assets.ts'

afterEach(() => { vi.unstubAllGlobals() })

const VERSION = '6.3.289'
const BASE = '/plugins/@deepseek-ai/dsh-client-ui-sidebar-documentpreview/assets'

/** Answer any asset request with the given bytes. */
function stubFetch(bytes: readonly number[]): Mock<(url: string) => Promise<Response>> {
  const fetch = vi.fn((_url: string) => Promise.resolve(new Response(new Uint8Array(bytes))))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

describe('PDF binary assets', () => {
  const manifest: PdfAssetManifest = {
    cMapUrl: ['sample.bcmap'],
    standardFontDataUrl: ['font.pfb'],
    wasmUrl: ['decoder.wasm'],
  }

  it('reads the ambient build manifest only when the factory is created', async () => {
    vi.stubGlobal('__DSH_PDFJS_ASSETS__', manifest)
    vi.stubGlobal('__DSH_PDFJS_VERSION__', VERSION)
    const fetch = stubFetch([1, 2, 3])
    const Factory = createPdfBinaryDataFactory()
    const factory = new Factory()
    expect(Array.from(await factory.fetch({ kind: 'cMapUrl', filename: 'sample.bcmap' }))).toEqual([1, 2, 3])
    expect(fetch).toHaveBeenCalledWith(`${BASE}/cmaps/sample.bcmap?v=${VERSION}`)
  })

  it('addresses each kind through its own directory', async () => {
    const fetch = stubFetch([9])
    const factory = new (createPdfBinaryDataFactory(manifest, VERSION))()
    await factory.fetch({ kind: 'standardFontDataUrl', filename: 'font.pfb' })
    await factory.fetch({ kind: 'wasmUrl', filename: 'decoder.wasm' })
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      `${BASE}/standard_fonts/font.pfb?v=${VERSION}`,
      `${BASE}/wasm/decoder.wasm?v=${VERSION}`,
    ])
  })

  it('never shares a buffer that PDF.js may transfer away', async () => {
    stubFetch([1, 2, 3])
    const factory = new (createPdfBinaryDataFactory(manifest, VERSION))()
    const first = await factory.fetch({ kind: 'cMapUrl', filename: 'sample.bcmap' })
    structuredClone(first, { transfer: [first.buffer] })
    expect(first.byteLength).toBe(0)
    expect(Array.from(await factory.fetch({ kind: 'cMapUrl', filename: 'sample.bcmap' }))).toEqual([1, 2, 3])
  })

  it.each(['../font.pfb', 'missing.bcmap', 'toString'])('rejects unadvertised filename %s without fetching', async (filename) => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const factory = new (createPdfBinaryDataFactory(manifest, VERSION))()
    await expect(factory.fetch({ kind: 'cMapUrl', filename })).rejects.toThrow('not bundled')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('fails the document when the host does not answer an advertised asset', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(null, { status: 404 }))))
    const factory = new (createPdfBinaryDataFactory(manifest, VERSION))()
    await expect(factory.fetch({ kind: 'cMapUrl', filename: 'sample.bcmap' }))
      .rejects.toThrow('cMapUrl/sample.bcmap answered 404')
  })

  it('percent-encodes a filename into the request URL', async () => {
    const fetch = stubFetch([1])
    const factory = new (createPdfBinaryDataFactory({
      ...manifest,
      cMapUrl: ['Adobe-Japan1 UCS2.bcmap'],
    }, VERSION))()
    await factory.fetch({ kind: 'cMapUrl', filename: 'Adobe-Japan1 UCS2.bcmap' })
    expect(fetch).toHaveBeenCalledWith(`${BASE}/cmaps/Adobe-Japan1%20UCS2.bcmap?v=${VERSION}`)
  })
})
