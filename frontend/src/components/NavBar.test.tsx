import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { NavBar } from './NavBar'

function renderWithCapabilities(capabilities: string[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(JSON.stringify({ user_id: 'SYN-USER', roles: [], capabilities }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  )
  return render(
    <BrowserRouter>
      <CapabilitiesProvider>
        <NavBar />
      </CapabilitiesProvider>
    </BrowserRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('NavBar mobile navigation', () => {
  it('starts collapsed and expands the Thai menu when the toggle is tapped', async () => {
    const user = userEvent.setup()
    render(
      <BrowserRouter>
        <NavBar />
      </BrowserRouter>,
    )

    const menu = screen.getByRole('list')
    expect(menu.className).not.toContain('is-open')

    const toggle = screen.getByRole('button', { name: 'เปิดเมนู' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    await user.click(toggle)

    expect(menu.className).toContain('is-open')
    expect(screen.getByRole('button', { name: 'ปิดเมนู' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
  })

  it('offers the fleet status dashboard as a plain menu link (Phase 7 Batch 7B2)', () => {
    render(
      <BrowserRouter>
        <NavBar />
      </BrowserRouter>,
    )

    expect(screen.getByRole('link', { name: 'ภาพรวมกองรถ' })).toHaveAttribute('href', '/dashboard')
  })

  it('offers the certificate expiry report right after the dashboard for can_view (Phase 7 Batch 7D2)', async () => {
    renderWithCapabilities(['can_view'])
    const link = await screen.findByRole('link', { name: 'ใบรับรองตามวันหมดอายุ' })
    expect(link).toHaveAttribute('href', '/reports/certificate-expiry')
    const labels = screen.getAllByRole('link').map((a) => a.textContent)
    expect(labels.indexOf('ใบรับรองตามวันหมดอายุ')).toBe(labels.indexOf('ภาพรวมกองรถ') + 1)
  })

  it('hides the certificate expiry report menu item without can_view', async () => {
    renderWithCapabilities(['can_report_repair'])
    // Let the provider's /me request resolve and apply before asserting absence.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20))
    })
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('link', { name: 'ภาพรวมกองรถ' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'ใบรับรองตามวันหมดอายุ' })).toBeNull()
  })

  it('closes the menu again after a link is chosen', async () => {
    const user = userEvent.setup()
    render(
      <BrowserRouter>
        <NavBar />
      </BrowserRouter>,
    )

    await user.click(screen.getByRole('button', { name: 'เปิดเมนู' }))
    await user.click(screen.getByRole('link', { name: 'สถานะระบบ' }))

    expect(screen.getByRole('list').className).not.toContain('is-open')
  })
})
