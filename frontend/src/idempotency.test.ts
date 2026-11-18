import { describe, expect, it, vi } from 'vitest'
import { newIdempotencyKey } from './idempotency'

const BACKEND_KEY_FORMAT = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/

describe('newIdempotencyKey', () => {
  it('uses randomUUID when the browser provides it', () => {
    vi.stubGlobal('crypto', { randomUUID: () => '123e4567-e89b-12d3-a456-426614174000' })
    expect(newIdempotencyKey()).toBe('123e4567-e89b-12d3-a456-426614174000')
  })

  it('still works over plain http, where randomUUID is missing', () => {
    vi.stubGlobal('crypto', { getRandomValues: (a: Uint8Array) => { a.forEach((_, i) => { a[i] = i + 1 }); return a } })
    const key = newIdempotencyKey()
    expect(key).toMatch(BACKEND_KEY_FORMAT)
    expect(key).toBe('k0102030405060708090a0b0c0d0e0f10')
  })

  it('still works if there is no crypto at all', () => {
    vi.stubGlobal('crypto', undefined)
    const a = newIdempotencyKey()
    const b = newIdempotencyKey()
    expect(a).toMatch(BACKEND_KEY_FORMAT)
    expect(a).not.toBe(b)
  })

  it('every fallback key is valid for the backend and different each time', () => {
    vi.stubGlobal('crypto', { getRandomValues: (a: Uint8Array) => { for (let i = 0; i < a.length; i++) a[i] = Math.floor(Math.random() * 256); return a } })
    const keys = new Set(Array.from({ length: 50 }, () => newIdempotencyKey()))
    expect(keys.size).toBe(50)
    for (const k of keys) expect(k).toMatch(BACKEND_KEY_FORMAT)
  })
})
