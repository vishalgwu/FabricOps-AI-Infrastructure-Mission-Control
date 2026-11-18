import { useEffect, useState } from 'react'

// A tiny hash router. The URL is the only navigation state, so a refresh (or a shared link) reopens
// the same page and the page reloads its data from the server.

export type Route =
  | { page: 'incidents' }
  | { page: 'incident'; id: string }
  | { page: 'run'; id: string }
  | { page: 'history' }
  | { page: 'about' }
  | { page: 'notfound'; path: string }

export function parseRoute(hash: string): Route {
  const path = hash.replace(/^#/, '') || '/'
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent)
  if (parts.length === 0 || (parts.length === 1 && parts[0] === 'incidents')) return { page: 'incidents' }
  if (parts[0] === 'incidents' && parts.length === 2) return { page: 'incident', id: parts[1] }
  if (parts[0] === 'runs' && parts.length === 2) return { page: 'run', id: parts[1] }
  if (parts.length === 1 && parts[0] === 'history') return { page: 'history' }
  if (parts.length === 1 && parts[0] === 'about') return { page: 'about' }
  return { page: 'notfound', path }
}

export const links = {
  incidents: () => '#/incidents',
  incident: (id: string) => `#/incidents/${encodeURIComponent(id)}`,
  run: (id: string) => `#/runs/${encodeURIComponent(id)}`,
  history: () => '#/history',
  about: () => '#/about',
}

export function navigate(href: string): void {
  window.location.hash = href.replace(/^#/, '')
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
