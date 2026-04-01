import { describe, it, expect } from 'vitest'
import { cn } from '../utils'

describe('cn()', () => {
  it('merges two class strings', () => {
    expect(cn('foo', 'bar')).toBe('foo bar')
  })

  it('omits falsy values', () => {
    expect(cn('foo', false, undefined, null, '', 'bar')).toBe('foo bar')
  })

  it('deduplicates conflicting Tailwind classes (last wins)', () => {
    expect(cn('px-2', 'px-4')).toBe('px-4')
  })

  it('handles an empty call', () => {
    expect(cn()).toBe('')
  })

  it('handles a single class', () => {
    expect(cn('text-sm')).toBe('text-sm')
  })

  it('merges conditional object syntax', () => {
    expect(cn('base', { active: true, disabled: false })).toBe('base active')
  })

  it('merges array syntax', () => {
    expect(cn(['a', 'b'], 'c')).toBe('a b c')
  })

  it('resolves conflicting padding classes correctly', () => {
    // twMerge should keep p-4 and discard p-2
    const result = cn('p-2', 'p-4')
    expect(result).toBe('p-4')
  })

  it('resolves conflicting background-color classes', () => {
    expect(cn('bg-red-500', 'bg-blue-500')).toBe('bg-blue-500')
  })
})
