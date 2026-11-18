import { describe, expect, it } from 'vitest'
import { failureReason, foldStages, formatDuration, formatTime, isActive } from './format'
import { event, stageEvents } from './test/fakeApi'
import { links, parseRoute } from './router'

describe('formatting', () => {
  it('shows times in UTC, to the second', () => {
    expect(formatTime('2026-03-10T14:00:00.123456Z')).toBe('2026-03-10 14:00:00Z')
    expect(formatTime('2026-03-10T16:00:00+02:00')).toBe('2026-03-10 14:00:00Z')
    expect(formatTime(null)).toBe('—')
    expect(formatTime('not a date')).toBe('not a date')
  })

  it('formats durations', () => {
    expect(formatDuration('2026-03-10T14:00:00Z', '2026-03-10T14:00:00.250Z')).toBe('250 ms')
    expect(formatDuration('2026-03-10T14:00:00Z', '2026-03-10T14:01:30Z')).toBe('90.0 s')
    expect(formatDuration('2026-03-10T14:00:00Z', null)).toBe('—')
  })

  it('knows which statuses are still active', () => {
    expect(['CREATED', 'RUNNING'].every((s) => isActive(s as 'CREATED'))).toBe(true)
    expect(['WAITING_APPROVAL', 'COMPLETE', 'ABSTAINED', 'FAILED', 'CANCELLED'].some((s) => isActive(s as 'FAILED'))).toBe(false)
  })
})

describe('stage timeline folding', () => {
  it('produces one row per stage, in order, with the latest state', () => {
    const rows = foldStages([...stageEvents(['load_incident', 'validate_scope']), event(9, 'status_changed', null)])
    expect(rows.map((r) => [r.stage, r.state])).toEqual([['load_incident', 'completed'], ['validate_scope', 'completed']])
  })

  it('shows a stage that has started but not finished, and one that failed', () => {
    const rows = foldStages([
      event(1, 'stage_started', { stage: 'collect_telemetry' }),
      event(2, 'stage_started', { stage: 'investigate' }),
      event(3, 'stage_failed', { stage: 'investigate', code: 'x', message: 'it broke' }),
    ])
    expect(rows.map((r) => r.state)).toEqual(['started', 'failed'])
    expect(rows[1].detail).toBe('it broke')
  })

  it('ignores events it cannot read', () => {
    expect(foldStages([event(1, 'stage_started', null), { ...event(2, 'stage_started'), detail: '{not json' }])).toEqual([])
  })

  it('finds the last failure reason', () => {
    expect(failureReason([event(1, 'stage_failed', { code: 'a', message: 'first' }), event(2, 'stage_failed', { code: 'b', message: 'second' })])).toEqual({ code: 'b', message: 'second' })
    expect(failureReason(stageEvents(['x']))).toBeNull()
  })
})

describe('router', () => {
  it('parses every page', () => {
    expect(parseRoute('')).toEqual({ page: 'incidents' })
    expect(parseRoute('#/')).toEqual({ page: 'incidents' })
    expect(parseRoute('#/incidents')).toEqual({ page: 'incidents' })
    expect(parseRoute('#/incidents/inc_1')).toEqual({ page: 'incident', id: 'inc_1' })
    expect(parseRoute('#/runs/run_1')).toEqual({ page: 'run', id: 'run_1' })
    expect(parseRoute('#/history')).toEqual({ page: 'history' })
    expect(parseRoute('#/about')).toEqual({ page: 'about' })
  })

  it('round-trips IDs with special characters and rejects unknown paths', () => {
    expect(parseRoute(links.run('a/b c'))).toEqual({ page: 'run', id: 'a/b c' })
    expect(parseRoute('#/nope/at/all')).toEqual({ page: 'notfound', path: '/nope/at/all' })
    expect(parseRoute('#/runs')).toEqual({ page: 'notfound', path: '/runs' })
  })
})
