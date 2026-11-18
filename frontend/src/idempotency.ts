/**
 * A fresh key for each "Start investigation" click, so a double click cannot start two investigations.
 *
 * `crypto.randomUUID` only exists in secure contexts (https or localhost). Opening the app from another
 * machine over plain http, for example http://192.168.1.20:5173, leaves it undefined and the button would
 * fail, so fall back to random bytes. The result always satisfies the backend's key format
 * (letters, digits, `_ . : -`, at most 64 characters).
 */
export function newIdempotencyKey(): string {
  const c: Crypto | undefined = typeof crypto === 'undefined' ? undefined : crypto
  if (c && typeof c.randomUUID === 'function') return c.randomUUID()
  const bytes = new Uint8Array(16)
  if (c && typeof c.getRandomValues === 'function') {
    c.getRandomValues(bytes)
  } else {
    for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256)
  }
  return 'k' + Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}
