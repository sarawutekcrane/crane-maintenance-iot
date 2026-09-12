import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('App shell', () => {
  it('renders the Thai navigation and home page by default', () => {
    render(
      <BrowserRouter>
        <App />
      </BrowserRouter>,
    )

    expect(screen.getByText('ระบบบำรุงรักษาเครน')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'ยินดีต้อนรับ' })).toBeInTheDocument()
  })
})
