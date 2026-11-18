import { useEffect, useState } from 'react'
import { fetchHealth, type HealthResponse } from '../api/client'

type State =
  | { kind: 'loading' }
  | { kind: 'ok'; data: HealthResponse }
  | { kind: 'error'; message: string }

export default function HealthStatus() {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    fetchHealth(controller.signal)
      .then((data) => setState({ kind: 'ok', data }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        setState({ kind: 'error', message: err instanceof Error ? err.message : 'Unknown error' })
      })
    return () => controller.abort()
  }, [])

  if (state.kind === 'loading') return <p>Checking backend…</p>
  if (state.kind === 'error') return <p role="alert">Backend unreachable: {state.message}</p>
  return (
    <p>
      Backend <strong>{state.data.status}</strong> ({state.data.service}, {state.data.environment})
    </p>
  )
}
