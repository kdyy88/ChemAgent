import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  validateSmiles,
  saltStrip,
  computeDescriptors,
  fetchSupportedFormats,
  build3DConformer,
  sdfSplit,
  getSdfSplitDownloadUrl,
  getSdfMergeDownloadUrl,
} from '../chem-api'

// ── Fetch mock helpers ─────────────────────────────────────────────────────────

function mockFetchOk(body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(body),
    status: 200,
    statusText: 'OK',
  })
}

function mockFetchFail(status = 500, statusText = 'Internal Server Error') {
  return vi.fn().mockResolvedValue({
    ok: false,
    json: () => Promise.reject(new Error('no body')),
    status,
    statusText,
  })
}

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetchOk({ is_valid: true }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// ── Pure URL builders ──────────────────────────────────────────────────────────

describe('getSdfSplitDownloadUrl()', () => {
  it('returns a URL containing the path and result_id', () => {
    const url = getSdfSplitDownloadUrl('abc-123')
    expect(url).toMatch('/api/babel/sdf-split-download')
    expect(url).toMatch('result_id=abc-123')
  })

  it('URL-encodes the result id', () => {
    const url = getSdfSplitDownloadUrl('id with spaces')
    expect(url).toContain('id%20with%20spaces')
  })
})

describe('getSdfMergeDownloadUrl()', () => {
  it('returns a URL containing the path and result_id', () => {
    const url = getSdfMergeDownloadUrl('merge-xyz')
    expect(url).toMatch('/api/babel/sdf-merge-download')
    expect(url).toMatch('result_id=merge-xyz')
  })
})

// ── validateSmiles ─────────────────────────────────────────────────────────────

describe('validateSmiles()', () => {
  it('POSTs to /api/rdkit/validate with JSON body', async () => {
    const mockFetch = mockFetchOk({ is_valid: true })
    vi.stubGlobal('fetch', mockFetch)

    await validateSmiles('CCO')

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit]
    expect(url).toMatch('/api/rdkit/validate')
    expect(init.method).toBe('POST')
    expect(init.headers).toMatchObject({ 'Content-Type': 'application/json' })
    expect(JSON.parse(init.body as string)).toEqual({ smiles: 'CCO' })
  })

  it('returns the parsed response on success', async () => {
    const payload = { is_valid: true, canonical_smiles: 'CCO' }
    vi.stubGlobal('fetch', mockFetchOk(payload))

    const result = await validateSmiles('CCO')
    expect(result).toEqual(payload)
  })

  it('throws on non-OK response', async () => {
    vi.stubGlobal('fetch', mockFetchFail(422, 'Unprocessable Entity'))
    await expect(validateSmiles('INVALID')).rejects.toThrow('HTTP 422')
  })
})

// ── saltStrip ─────────────────────────────────────────────────────────────────

describe('saltStrip()', () => {
  it('POSTs to /api/rdkit/salt-strip', async () => {
    const mockFetch = mockFetchOk({ is_valid: true })
    vi.stubGlobal('fetch', mockFetch)

    await saltStrip('CCO.Cl')

    const [url] = mockFetch.mock.calls[0] as [string, RequestInit]
    expect(url).toMatch('/api/rdkit/salt-strip')
  })

  it('throws on HTTP 500', async () => {
    vi.stubGlobal('fetch', mockFetchFail(500))
    await expect(saltStrip('bad')).rejects.toThrow('HTTP 500')
  })
})

// ── computeDescriptors ────────────────────────────────────────────────────────

describe('computeDescriptors()', () => {
  it('POSTs to /api/rdkit/descriptors with smiles and name', async () => {
    const mockFetch = mockFetchOk({ is_valid: true })
    vi.stubGlobal('fetch', mockFetch)

    await computeDescriptors('CCO', 'Ethanol')

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit]
    expect(url).toMatch('/api/rdkit/descriptors')
    expect(JSON.parse(init.body as string)).toMatchObject({ smiles: 'CCO', name: 'Ethanol' })
  })

  it('defaults name to empty string', async () => {
    const mockFetch = mockFetchOk({ is_valid: true })
    vi.stubGlobal('fetch', mockFetch)

    await computeDescriptors('CCO')

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(init.body as string).name).toBe('')
  })
})

// ── fetchSupportedFormats ─────────────────────────────────────────────────────

describe('fetchSupportedFormats()', () => {
  it('sends a GET request to /api/babel/formats', async () => {
    const payload = { input_formats: [], output_formats: [], input_count: 0, output_count: 0 }
    const mockFetch = mockFetchOk(payload)
    vi.stubGlobal('fetch', mockFetch)

    await fetchSupportedFormats()

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit | undefined]
    expect(url).toMatch('/api/babel/formats')
    // GET — no body
    expect(init?.body).toBeUndefined()
  })

  it('throws on non-OK', async () => {
    vi.stubGlobal('fetch', mockFetchFail(503, 'Service Unavailable'))
    await expect(fetchSupportedFormats()).rejects.toThrow('HTTP 503')
  })
})

// ── build3DConformer ──────────────────────────────────────────────────────────

describe('build3DConformer()', () => {
  it('sends correct default params', async () => {
    const mockFetch = mockFetchOk({ is_valid: true })
    vi.stubGlobal('fetch', mockFetch)

    await build3DConformer('CCO')

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit]
    expect(url).toMatch('/api/babel/conformer3d')
    const body = JSON.parse(init.body as string)
    expect(body.smiles).toBe('CCO')
    expect(body.name).toBe('')
    expect(body.forcefield).toBe('mmff94')
    expect(body.steps).toBe(500)
  })

  it('accepts custom name, forcefield and steps', async () => {
    const mockFetch = mockFetchOk({ is_valid: true })
    vi.stubGlobal('fetch', mockFetch)

    await build3DConformer('CCO', 'Ethanol', 'uff', 1000)

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit]
    const body = JSON.parse(init.body as string)
    expect(body.name).toBe('Ethanol')
    expect(body.forcefield).toBe('uff')
    expect(body.steps).toBe(1000)
  })
})

// ── sdfSplit ──────────────────────────────────────────────────────────────────

describe('sdfSplit()', () => {
  it('sends a FormData POST to /api/babel/sdf-split', async () => {
    const mockFetch = mockFetchOk({ is_valid: true, molecule_count: 1 })
    vi.stubGlobal('fetch', mockFetch)

    const file = new File(['data'], 'test.sdf', { type: 'chemical/x-mdl-sdfile' })
    await sdfSplit(file)

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit]
    expect(url).toMatch('/api/babel/sdf-split')
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
    // Content-Type header must NOT be set manually (browser sets multipart boundary)
    const headers = init.headers as Record<string, string> | undefined
    expect(headers?.['Content-Type']).toBeUndefined()
  })
})
