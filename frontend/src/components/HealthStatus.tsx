import { useEffect, useState } from 'react'
import { fetchHealth } from '../api/client'

type State = { kind: 'loading' } | { kind: 'ok'; env: string } | { kind: 'error' }

export default function HealthStatus() {
  const [state, setState] = useState<State>({ kind: 'loading' })
  useEffect(() => {
    const controller = new AbortController()
    fetchHealth(controller.signal).then(
      (h) => !controller.signal.aborted && setState({ kind: 'ok', env: h.environment }),
      () => !controller.signal.aborted && setState({ kind: 'error' }),
    )
    return () => controller.abort()
  }, [])
  if (state.kind === 'loading') return <span className="health-dot">Checking backend…</span>
  if (state.kind === 'error') return <span className="health-dot health-bad" role="alert">Backend unreachable</span>
  return <span className="health-dot health-ok">Backend ok ({state.env})</span>
}
