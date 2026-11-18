import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api } from './api/client'
import type { EvidenceRecord, ProposalView, Report, Run, RunEvent } from './api/types'
import { isActive } from './format'

export type Async<T> =
  | { state: 'loading' }
  | { state: 'ready'; data: T }
  | { state: 'error'; error: ApiError }

export const toApiError = (err: unknown): ApiError =>
  err instanceof ApiError ? err : new ApiError(0, 'unexpected', err instanceof Error ? err.message : 'Something went wrong')

const LOADING = { state: 'loading' } as const

/** Load something from the server when `key` changes. `reload` fetches it again. */
export function useLoad<T>(load: (signal: AbortSignal) => Promise<T>, key: string): { result: Async<T>; reload: () => void } {
  const [tick, setTick] = useState(0)
  const id = `${key}#${tick}`
  // The result is stored together with the request it belongs to, so a stale answer is never shown
  // for a newer request: until the new answer arrives, `result` is simply "loading".
  const [stored, setStored] = useState<{ id: string; result: Async<T> } | null>(null)
  const loadRef = useRef(load)
  useEffect(() => {
    loadRef.current = load
  })
  useEffect(() => {
    const controller = new AbortController()
    loadRef.current(controller.signal).then(
      (data) => !controller.signal.aborted && setStored({ id, result: { state: 'ready', data } }),
      (err: unknown) => !controller.signal.aborted && setStored({ id, result: { state: 'error', error: toApiError(err) } }),
    )
    return () => controller.abort()
  }, [id])
  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { result: stored && stored.id === id ? stored.result : LOADING, reload }
}

export interface RunData {
  run: Run
  events: RunEvent[]
  report: Report | null
  evidence: EvidenceRecord[]
  proposal: ProposalView | null
}

const POLL_ACTIVE_MS = 1000
const POLL_WAITING_MS = 10000

/**
 * Everything the run page shows, always read from the server (so a refresh restores it).
 * While the run is queued or running it polls; events are fetched incrementally with `after_seq`.
 * While it waits for approval it polls slowly, so an expired approval shows up on its own.
 * `reload` re-reads everything without blanking the page.
 */
export function useRunData(runId: string, pollActiveMs = POLL_ACTIVE_MS, pollWaitingMs = POLL_WAITING_MS) {
  const [stored, setStored] = useState<{ runId: string; result: Async<RunData> } | null>(null)
  const events = useRef<{ runId: string; list: RunEvent[]; lastSeq: number }>({ runId, list: [], lastSeq: 0 })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller
    let timer: ReturnType<typeof setTimeout> | undefined
    if (events.current.runId !== runId) events.current = { runId, list: [], lastSeq: 0 }

    const cycle = async () => {
      try {
        const run = await api.getRun(runId, signal)
        const fresh = await api.getEvents(runId, events.current.lastSeq, signal)
        if (fresh.events.length) {
          events.current.list = [...events.current.list, ...fresh.events]
          events.current.lastSeq = fresh.last_seq
        }
        // A report, evidence and proposal can exist as soon as the run has left CREATED/RUNNING.
        let report: Report | null = null
        let evidence: EvidenceRecord[] = []
        let proposal: ProposalView | null = null
        if (!isActive(run.status)) {
          ;[report, evidence, proposal] = await Promise.all([
            api.getReport(runId, signal),
            api.listEvidence(runId, signal),
            api.getProposal(runId, signal),
          ])
        }
        if (signal.aborted) return
        setStored({ runId, result: { state: 'ready', data: { run, events: events.current.list, report, evidence, proposal } } })
        const wait = isActive(run.status) ? pollActiveMs : run.status === 'WAITING_APPROVAL' ? pollWaitingMs : 0
        if (wait > 0) timer = setTimeout(() => void cycle(), wait)
      } catch (err) {
        if (signal.aborted) return
        setStored({ runId, result: { state: 'error', error: toApiError(err) } })
      }
    }
    void cycle()
    return () => {
      controller.abort()
      if (timer) clearTimeout(timer)
    }
  }, [runId, tick, pollActiveMs, pollWaitingMs])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  const result: Async<RunData> = stored && stored.runId === runId ? stored.result : LOADING
  return { result, reload }
}
