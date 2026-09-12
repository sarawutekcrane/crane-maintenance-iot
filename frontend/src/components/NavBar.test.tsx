import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { NavBar } from './NavBar'

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
