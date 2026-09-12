import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FormField } from './FormField'

describe('FormField', () => {
  it('associates the Thai label with its input via htmlFor/id', () => {
    render(
      <FormField label="ชื่อผู้ตรวจ" htmlFor="inspector-name">
        <input id="inspector-name" />
      </FormField>,
    )

    expect(screen.getByLabelText('ชื่อผู้ตรวจ')).toBeInTheDocument()
  })

  it('shows an error message with role=alert when provided', () => {
    render(
      <FormField label="ชื่อผู้ตรวจ" htmlFor="inspector-name" error="กรุณากรอกข้อมูล">
        <input id="inspector-name" />
      </FormField>,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('กรุณากรอกข้อมูล')
  })
})
