import { describe, it, expect } from 'vitest'
import { parseTodoLines } from '../TodoChecklist'

describe('parseTodoLines()', () => {
  it('parses checked items', () => {
    const { items, hasCheckboxes } = parseTodoLines('- [x] Step 1 done')
    expect(hasCheckboxes).toBe(true)
    expect(items).toHaveLength(1)
    expect(items[0]).toEqual({ checked: true, label: 'Step 1 done' })
  })

  it('parses unchecked items', () => {
    const { items } = parseTodoLines('- [ ] Step 2 pending')
    expect(items[0]).toEqual({ checked: false, label: 'Step 2 pending' })
  })

  it('parses mixed checklist', () => {
    const text = '- [x] Fetch SMILES\n- [x] Analyze molecule\n- [ ] Draw structure\n- [ ] Generate report'
    const { items, hasCheckboxes } = parseTodoLines(text)
    expect(hasCheckboxes).toBe(true)
    expect(items).toHaveLength(4)
    expect(items[0].checked).toBe(true)
    expect(items[1].checked).toBe(true)
    expect(items[2].checked).toBe(false)
    expect(items[3].checked).toBe(false)
  })

  it('handles uppercase X', () => {
    const { items } = parseTodoLines('- [X] Done task')
    expect(items[0].checked).toBe(true)
  })

  it('returns hasCheckboxes=false for plain text', () => {
    const { items, hasCheckboxes } = parseTodoLines('No checkboxes here\njust text')
    expect(hasCheckboxes).toBe(false)
    expect(items).toHaveLength(2)
  })

  it('handles empty string', () => {
    const { items, hasCheckboxes } = parseTodoLines('')
    expect(hasCheckboxes).toBe(false)
    expect(items).toHaveLength(0)
  })

  it('skips blank lines', () => {
    const text = '- [x] A\n\n- [ ] B\n  \n- [x] C'
    const { items } = parseTodoLines(text)
    expect(items).toHaveLength(3)
  })

  it('handles lines without checkbox syntax as plain items', () => {
    const text = '- [x] Done\nSome header\n- [ ] Pending'
    const { items, hasCheckboxes } = parseTodoLines(text)
    expect(hasCheckboxes).toBe(true)
    expect(items).toHaveLength(3)
    expect(items[0].checked).toBe(true)
    expect(items[1]).toEqual({ checked: false, label: 'Some header' })
    expect(items[2].checked).toBe(false)
  })

  it('trims whitespace from lines', () => {
    const { items } = parseTodoLines('  - [x] Indented task  ')
    expect(items[0].label).toBe('Indented task')
  })
})
