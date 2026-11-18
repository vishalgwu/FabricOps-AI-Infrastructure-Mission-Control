import type { EvidenceRecord } from '../api/types'
import { formatTime } from '../format'
import { Section, SyntheticTag } from './Common'
import { RefChip, type Selection } from './Inspector'

export function EvidenceTable({
  evidence,
  selection,
  onSelect,
}: {
  evidence: EvidenceRecord[]
  selection: Selection
  onSelect: (s: Selection) => void
}) {
  return (
    <Section id="evidence" title={`Evidence collected (${evidence.length})`} hint="Every record the read-only tools returned for this run, with the host and when it was observed.">
      {evidence.length === 0 ? (
        <p className="state state-empty">No evidence was collected for this run.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Host</th>
                <th>Kind</th>
                <th>What</th>
                <th>Observed at</th>
                <th>ID</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {evidence.map((e) => (
                <tr key={e.id}>
                  <td>{e.host_id}</td>
                  <td>{e.source_type}</td>
                  <td>{describe(e)}</td>
                  <td>{formatTime(e.observed_at)}</td>
                  <td>
                    <RefChip kind="evidence" id={e.id} selected={selection} onSelect={onSelect} />
                  </td>
                  <td>{e.synthetic ? <SyntheticTag /> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  )
}

function describe(e: EvidenceRecord): string {
  const p = e.payload
  if (e.source_type === 'metric') {
    const latest = p.latest_value
    return `${String(p.metric)} (${String(p.source)}): ${latest === null || latest === undefined ? 'no value reported' : `${String(latest)} ${String(p.unit)}`}`
  }
  if (e.source_type === 'log') return `${String(p.level)} log from ${String(p.source)}`
  return `configuration from ${String(p.source)}`
}
