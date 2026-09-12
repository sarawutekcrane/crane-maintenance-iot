import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusBadge } from './StatusBadge'

describe('StatusBadge', () => {
  it('renders the given Thai label', () => {
    render(<StatusBadge label="พร้อมใช้งาน" tone="success" />)
    expect(screen.getByText('พร้อมใช้งาน')).toBeInTheDocument()
  })
})
