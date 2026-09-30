import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AssetType } from '../lib/types'
import { AssetSearchSelect } from './AssetSearchSelect'

// Web/API Phase 7 Batch 7G2 (DEC-8(b)). Every response is deferred and
// resolved by the test, and the 300 ms debounce runs on fake timers, so
// response ordering is deterministic. All fixtures are synthetic.

interface PendingCall {
  url: URL
  method: string
  respond: (body: unknown, status?: number) => Promise<void>
}

function fakeResponse(body: unknown, status: number) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

async function flush() {
  for (let i = 0; i < 10; i += 1) await Promise.resolve()
}

function installFetch() {
  const calls: PendingCall[] = []
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    return new Promise((resolve) => {
      calls.push({
        url,
        method: (init?.method ?? 'GET').toUpperCase(),
        respond: async (body: unknown, status = 200) => {
          await act(async () => {
            resolve(fakeResponse(body, status))
            await flush()
          })
        },
      })
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

const failure = { error: { code: 'VEHICLE_MASTER_DATA_INVALID', message: 'x', request_id: 'req-1' } }

function vehiclePage(...items: [string, string][]) {
  return {
    items: items.map(([vehicle_id, machine_no]) => ({
      vehicle_id,
      machine_no,
      model_id: 'SYN-MODEL',
      serial_number: null,
      operational_status: 'READY',
      created_at: '2026-01-15T08:00:00Z',
      updated_at: '2026-01-15T08:00:00Z',
    })),
    page: 1,
    page_size: 10,
    total_items: items.length,
  }
}

function equipmentPage(...items: [string, string][]) {
  return {
    items: items.map(([equipment_id, name]) => ({ equipment_id, name })),
    page: 1,
    page_size: 10,
    total_items: items.length,
  }
}

const pageFor = (type: AssetType, ...items: [string, string][]) =>
  type === 'VEHICLE' ? vehiclePage(...items) : equipmentPage(...items)

async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms)
    await flush()
  })
}

function type(text: string) {
  act(() => {
    fireEvent.change(screen.getByLabelText('ค้นหายานพาหนะ/อุปกรณ์'), { target: { value: text } })
  })
}

function renderSelect(assetType: AssetType = 'VEHICLE', assetId = '') {
  const onChange = vi.fn()
  const view = render(
    <AssetSearchSelect id="picker" assetType={assetType} assetId={assetId} onChangeAssetId={onChange} />,
  )
  const rerender = (nextType: AssetType, nextId = '') =>
    view.rerender(
      <AssetSearchSelect id="picker" assetType={nextType} assetId={nextId} onChangeAssetId={onChange} />,
    )
  return { onChange, rerender, unmount: view.unmount }
}

const option = (label: string) => screen.queryByRole('button', { name: label })
const optionButtons = () =>
  screen.queryAllByRole('button').filter((b) => b.textContent?.includes(' — '))
const errorHint = () => screen.queryByRole('alert')
const searching = () => screen.queryByText('กำลังค้นหา...')

describe('AssetSearchSelect', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  for (const assetType of ['VEHICLE', 'EQUIPMENT'] as AssetType[]) {
    const endpoint = assetType === 'VEHICLE' ? '/api/v1/vehicles' : '/api/v1/equipment'
    const noun = assetType === 'VEHICLE' ? 'ยานพาหนะ' : 'เครื่องมือ/อุปกรณ์'

    it(`[${assetType}] success then failure removes the old options and shows an error with retry`, async () => {
      const calls = installFetch()
      renderSelect(assetType)
      await advance(300)
      expect(calls).toHaveLength(1)
      expect(calls[0].url.pathname).toBe(endpoint)
      expect(calls[0].url.searchParams.get('page_size')).toBe('10')
      expect(calls[0].url.searchParams.has('q')).toBe(false)
      await calls[0].respond(pageFor(assetType, ['SYN-A', 'Alpha']))
      expect(option('SYN-A — Alpha')).toBeInTheDocument()

      type('  SYN-B ')
      await advance(300)
      expect(calls[1].url.searchParams.get('q')).toBe('SYN-B')
      await calls[1].respond(failure, 500)
      expect(errorHint()).toHaveTextContent(`ค้นหา${noun}ไม่สำเร็จ จึงไม่แสดงรายการให้เลือก`)
      expect(optionButtons()).toHaveLength(0)
      expect(screen.getByRole('button', { name: 'ลองค้นหาอีกครั้ง' })).toBeInTheDocument()
      expect(searching()).not.toBeInTheDocument()
    })

    it(`[${assetType}] successful empty result differs from failure`, async () => {
      const calls = installFetch()
      renderSelect(assetType)
      await advance(300)
      await calls[0].respond(pageFor(assetType))
      expect(screen.getByText(`ไม่พบ${noun}ที่ตรงกับคำค้น`)).toBeInTheDocument()
      expect(errorHint()).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'ลองค้นหาอีกครั้ง' })).not.toBeInTheDocument()

      type('x')
      await advance(300)
      await calls[1].respond(failure, 503)
      expect(errorHint()).toBeInTheDocument()
      expect(screen.queryByText(`ไม่พบ${noun}ที่ตรงกับคำค้น`)).not.toBeInTheDocument()
    })

    it(`[${assetType}] explicit retry makes exactly one request for the current input`, async () => {
      const calls = installFetch()
      renderSelect(assetType)
      type('SYN-R')
      await advance(300)
      expect(calls).toHaveLength(1)
      await calls[0].respond({}, 500)
      expect(errorHint()).toBeInTheDocument()
      // No automatic retry.
      await advance(5000)
      expect(calls).toHaveLength(1)

      act(() => {
        fireEvent.click(screen.getByRole('button', { name: 'ลองค้นหาอีกครั้ง' }))
      })
      expect(calls).toHaveLength(2)
      expect(calls[1].url.pathname).toBe(endpoint)
      expect(calls[1].url.searchParams.get('q')).toBe('SYN-R')
      expect(errorHint()).not.toBeInTheDocument()
      expect(searching()).toBeInTheDocument()
      await advance(1000)
      expect(calls).toHaveLength(2) // no duplicate debounced request
      await calls[1].respond(pageFor(assetType, ['SYN-R1', 'Recovered']))
      expect(option('SYN-R1 — Recovered')).toBeInTheDocument()
      expect(calls.every((c) => c.method === 'GET')).toBe(true)
    })
  }

  it('hides the previous options immediately on edit, before the 300 ms debounce elapses', async () => {
    const calls = installFetch()
    renderSelect()
    await advance(300)
    await calls[0].respond(vehiclePage(['SYN-1', 'M-1'], ['SYN-2', 'M-2']))
    expect(optionButtons()).toHaveLength(2)

    type('SYN-2')
    // Same render as the keystroke: nothing from the earlier query is selectable.
    expect(optionButtons()).toHaveLength(0)
    expect(searching()).toBeInTheDocument()
    await advance(299)
    expect(calls).toHaveLength(1)
    expect(optionButtons()).toHaveLength(0)
    await advance(1)
    expect(calls).toHaveLength(2)
  })

  it('ignores an old response that resolves during the next debounce interval', async () => {
    const calls = installFetch()
    renderSelect()
    type('A')
    await advance(300)
    expect(calls).toHaveLength(1)
    type('AB')
    await advance(100)
    await calls[0].respond(vehiclePage(['SYN-OLD', 'old']))
    expect(option('SYN-OLD — old')).not.toBeInTheDocument()
    expect(searching()).toBeInTheDocument()
    await advance(200)
    expect(calls).toHaveLength(2)
    await calls[1].respond(vehiclePage(['SYN-NEW', 'new']))
    expect(option('SYN-NEW — new')).toBeInTheDocument()
    expect(optionButtons()).toHaveLength(1)
  })

  it('an older success never overwrites a newer success', async () => {
    const calls = installFetch()
    renderSelect()
    type('A')
    await advance(300)
    type('B')
    await advance(300)
    expect(calls.map((c) => c.url.searchParams.get('q'))).toEqual(['A', 'B'])
    await calls[1].respond(vehiclePage(['SYN-B', 'b']))
    await calls[0].respond(vehiclePage(['SYN-A', 'a']))
    expect(option('SYN-B — b')).toBeInTheDocument()
    expect(option('SYN-A — a')).not.toBeInTheDocument()
  })

  it('an older success never overwrites a newer failure', async () => {
    const calls = installFetch()
    renderSelect()
    type('A')
    await advance(300)
    type('B')
    await advance(300)
    await calls[1].respond(failure, 500)
    await calls[0].respond(vehiclePage(['SYN-A', 'a']))
    expect(errorHint()).toBeInTheDocument()
    expect(optionButtons()).toHaveLength(0)
  })

  it('an older failure never clears a newer success', async () => {
    const calls = installFetch()
    renderSelect()
    type('A')
    await advance(300)
    type('B')
    await advance(300)
    await calls[1].respond(vehiclePage(['SYN-B', 'b']))
    await calls[0].respond(failure, 500)
    expect(option('SYN-B — b')).toBeInTheDocument()
    expect(errorHint()).not.toBeInTheDocument()
  })

  it('switching asset type hides vehicle options at once and ignores the vehicle response', async () => {
    const calls = installFetch()
    const { rerender } = renderSelect('VEHICLE')
    await advance(300)
    await calls[0].respond(vehiclePage(['SYN-V1', 'v1']))
    expect(option('SYN-V1 — v1')).toBeInTheDocument()

    type('SYN')
    await advance(300)
    expect(calls[1].url.pathname).toBe('/api/v1/vehicles')
    act(() => rerender('EQUIPMENT'))
    // During the debounce: no vehicle option is shown or selectable.
    expect(optionButtons()).toHaveLength(0)
    await calls[1].respond(vehiclePage(['SYN-V2', 'v2']))
    expect(optionButtons()).toHaveLength(0)
    expect(screen.getByLabelText('ค้นหายานพาหนะ/อุปกรณ์')).toHaveValue('')

    await advance(300)
    expect(calls).toHaveLength(3)
    expect(calls[2].url.pathname).toBe('/api/v1/equipment')
    await calls[2].respond(equipmentPage(['SYN-E1', 'Sling']))
    expect(option('SYN-E1 — Sling')).toBeInTheDocument()
    expect(option('SYN-V2 — v2')).not.toBeInTheDocument()
  })

  it('selection passes the original id, and nothing obsolete comes back afterwards', async () => {
    const calls = installFetch()
    const { onChange, rerender } = renderSelect()
    type('0012')
    await advance(300)
    await calls[0].respond(vehiclePage(['SYN-0012', 'TC-12']))
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: 'SYN-0012 — TC-12' }))
    })
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith('SYN-0012')

    act(() => rerender('VEHICLE', 'SYN-0012'))
    expect(screen.getByText(/เลือกแล้ว: SYN-0012/)).toBeInTheDocument()
    await advance(1000)
    expect(calls).toHaveLength(1) // no search while an asset is selected

    act(() => {
      fireEvent.click(screen.getByRole('button', { name: 'เปลี่ยน' }))
    })
    expect(onChange).toHaveBeenLastCalledWith('')
    act(() => rerender('VEHICLE', ''))
    // The earlier options are not restored; a fresh search is made.
    expect(optionButtons()).toHaveLength(0)
    await advance(300)
    expect(calls).toHaveLength(2)
    expect(calls[1].url.searchParams.has('q')).toBe(false)
  })

  it('a response arriving after unmount is ignored without errors', async () => {
    const calls = installFetch()
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { unmount } = renderSelect()
    await advance(300)
    unmount()
    await calls[0].respond(vehiclePage(['SYN-A', 'a']))
    await advance(1000)
    expect(calls).toHaveLength(1)
    expect(consoleError).not.toHaveBeenCalled()
    consoleError.mockRestore()
  })

  // Batch 7G2 correction: stored results must belong to the CURRENT search
  // cycle, not merely to an equal (asset type, query) input.
  for (const assetType of ['VEHICLE', 'EQUIPMENT'] as AssetType[]) {
    it(`[${assetType}] returning to an earlier query before the debounce does not revive its old options`, async () => {
      const calls = installFetch()
      renderSelect(assetType)
      type('A')
      await advance(300)
      await calls[0].respond(pageFor(assetType, ['SYN-OLD-A', 'old']))
      expect(option('SYN-OLD-A — old')).toBeInTheDocument()

      type('B')
      await advance(100)
      type('A')
      // Same input text as the stored result, but a new search cycle.
      expect(option('SYN-OLD-A — old')).not.toBeInTheDocument()
      expect(optionButtons()).toHaveLength(0)
      expect(searching()).toBeInTheDocument()
      await advance(299)
      expect(calls).toHaveLength(1)
      expect(optionButtons()).toHaveLength(0)
      await advance(1)
      expect(calls).toHaveLength(2)
      expect(calls[1].url.searchParams.get('q')).toBe('A')
      expect(optionButtons()).toHaveLength(0)
      await calls[1].respond(pageFor(assetType, ['SYN-NEW-A', 'fresh']))
      expect(option('SYN-NEW-A — fresh')).toBeInTheDocument()
      expect(option('SYN-OLD-A — old')).not.toBeInTheDocument()
    })

    it(`[${assetType}] an old failure for the same query is not shown again after returning to it`, async () => {
      const calls = installFetch()
      renderSelect(assetType)
      type('A')
      await advance(300)
      await calls[0].respond(failure, 500)
      expect(errorHint()).toBeInTheDocument()

      type('B')
      await advance(100)
      type('A')
      expect(errorHint()).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'ลองค้นหาอีกครั้ง' })).not.toBeInTheDocument()
      expect(searching()).toBeInTheDocument()
      await advance(300)
      expect(calls).toHaveLength(2)
      expect(errorHint()).not.toBeInTheDocument()
      await calls[1].respond(pageFor(assetType, ['SYN-A', 'recovered']))
      expect(option('SYN-A — recovered')).toBeInTheDocument()
      expect(errorHint()).not.toBeInTheDocument()
    })
  }

  for (const [first, second] of [
    ['VEHICLE', 'EQUIPMENT'],
    ['EQUIPMENT', 'VEHICLE'],
  ] as [AssetType, AssetType][]) {
    it(`${first} -> ${second} -> ${first} before a replacement completes does not revive the old options`, async () => {
      const calls = installFetch()
      const { rerender } = renderSelect(first)
      await advance(300)
      await calls[0].respond(pageFor(first, ['SYN-FIRST', 'old']))
      expect(option('SYN-FIRST — old')).toBeInTheDocument()

      // Back within the debounce (empty query both times).
      act(() => rerender(second))
      await advance(100)
      act(() => rerender(first))
      expect(option('SYN-FIRST — old')).not.toBeInTheDocument()
      expect(optionButtons()).toHaveLength(0)
      await advance(299)
      expect(optionButtons()).toHaveLength(0)
      expect(calls).toHaveLength(1)
      await advance(1)
      expect(calls).toHaveLength(2)
      expect(calls[1].url.pathname).toBe(calls[0].url.pathname)

      // Away again while that replacement is in flight, and back again.
      act(() => rerender(second))
      await advance(300)
      expect(calls).toHaveLength(3)
      act(() => rerender(first))
      await calls[1].respond(pageFor(first, ['SYN-STALE', 'in-flight']))
      await calls[2].respond(pageFor(second, ['SYN-OTHER', 'other']))
      expect(optionButtons()).toHaveLength(0)
      await advance(300)
      expect(calls).toHaveLength(4)
      await calls[3].respond(pageFor(first, ['SYN-FRESH', 'fresh']))
      expect(option('SYN-FRESH — fresh')).toBeInTheDocument()
      expect(optionButtons()).toHaveLength(1)
    })
  }

  it('re-opening the search after a parent-driven selection does not revive earlier options', async () => {
    const calls = installFetch()
    const { rerender } = renderSelect('VEHICLE')
    await advance(300)
    await calls[0].respond(vehiclePage(['SYN-1', 'one']))
    expect(option('SYN-1 — one')).toBeInTheDocument()

    // The parent sets and then clears the selection (e.g. a kept prior
    // selection followed by "เปลี่ยน"), with no new search completing.
    act(() => rerender('VEHICLE', 'SYN-KEPT'))
    act(() => rerender('VEHICLE', ''))
    expect(optionButtons()).toHaveLength(0)
    await advance(300)
    expect(calls).toHaveLength(2)
    await calls[1].respond(vehiclePage(['SYN-2', 'two']))
    expect(option('SYN-2 — two')).toBeInTheDocument()
    expect(option('SYN-1 — one')).not.toBeInTheDocument()
  })
})
