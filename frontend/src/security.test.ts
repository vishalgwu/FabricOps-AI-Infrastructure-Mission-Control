import { describe, expect, it } from 'vitest'

// Everything in src (apart from tests) ends up in the browser bundle. It must never carry a secret,
// and the only environment value it may read is the public API URL.
const files = import.meta.glob(['./**/*.ts', './**/*.tsx', '!./**/*.test.ts', '!./**/*.test.tsx', '!./test/**'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

describe('browser code carries no secrets', () => {
  it('scans the real source files', () => {
    expect(Object.keys(files).length).toBeGreaterThan(10)
  })

  it('has no API keys, tokens or provider names', () => {
    for (const [name, text] of Object.entries(files)) {
      expect(text, name).not.toMatch(/sk-ant-|sk-[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{16,}/)
      expect(text, name).not.toMatch(/ANTHROPIC|LLM_API_KEY|api[_-]?key/i)
    }
  })

  it('reads only VITE_API_BASE_URL from the environment', () => {
    const used = new Set<string>()
    for (const text of Object.values(files)) {
      for (const m of text.matchAll(/import\.meta\.env\.([A-Za-z_]+)/g)) used.add(m[1])
    }
    expect([...used]).toEqual(['VITE_API_BASE_URL'])
  })

  it('stores nothing sensitive in the browser (only the demo reviewer name)', () => {
    for (const text of Object.values(files)) {
      for (const m of text.matchAll(/(?:localStorage|sessionStorage)\.(?:set|get)Item\(\s*([A-Za-z_'"`.]+)/g)) {
        expect(m[1]).toMatch(/REVIEWER_KEY/)
      }
    }
  })

  it('never renders model, log or document text as HTML', () => {
    for (const [name, text] of Object.entries(files)) {
      expect(text, name).not.toMatch(/dangerouslySetInnerHTML|innerHTML\s*=|\beval\(|new Function\(/)
    }
  })
})
