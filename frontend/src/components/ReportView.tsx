import type { Report } from '../api/types'
import { Section } from './Common'
import { RefChip, type Selection } from './Inspector'

interface Props {
  report: Report
  selection: Selection
  onSelect: (s: Selection) => void
}

export function ReportView({ report, selection, onSelect }: Props) {
  const chip = (kind: 'evidence' | 'citation', id: string) => (
    <RefChip key={`${kind}-${id}`} kind={kind} id={id} selected={selection} onSelect={onSelect} />
  )

  if (report.insufficient_evidence) {
    return (
      <>
        <Section id="missing" title="What is missing" hint="FabricOps did not guess. These are the pieces of evidence needed before any cause can be proposed.">
          <ul className="plain">
            {report.missing_evidence.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </Section>
        <Limitations items={report.limitations} />
      </>
    )
  }

  return (
    <>
      <Section id="facts" title="Facts from the evidence" hint="Observations: what the collected records actually show. Click an ID to open the record.">
        {report.observations.length === 0 ? <p className="state state-empty">No observations were reported.</p> : (
          <ul className="plain">
            {report.observations.map((o, n) => (
              <li key={n} className="fact">
                <p>{o.text}</p>
                <p className="refs">Evidence: {o.evidence_ids.map((id) => chip('evidence', id))}</p>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="hypotheses" title="Hypotheses (suggestions, not established facts)" hint="Interpretations that fit the observations but are not proven. Each lists what supports it and what argues against it.">
        {report.hypotheses.length === 0 ? <p className="state state-empty">No hypotheses were reported.</p> : (
          <ul className="plain">
            {report.hypotheses.map((h, n) => (
              <li key={n} className="hypothesis">
                <p className="hypothesis-statement">{h.statement}</p>
                <p className="refs">Supporting evidence: {h.supporting_evidence_ids.map((id) => chip('evidence', id))}</p>
                <div className="counter">
                  <strong>Counterevidence and unknowns</strong>
                  {h.counterevidence.length === 0 ? (
                    <p>None was reported. That does not mean none exists.</p>
                  ) : (
                    <ul>
                      {h.counterevidence.map((c) => (
                        <li key={c}>{c}</li>
                      ))}
                    </ul>
                  )}
                </div>
                {h.citations.length > 0 ? <p className="refs">Documentation: {h.citations.map((id) => chip('citation', id))}</p> : null}
                <p className="hint">The model's stated confidence is “{h.confidence}”. It is the model's own wording, is not calibrated, and is not a probability.</p>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {report.missing_evidence.length > 0 ? (
        <Section id="missing" title="Still missing">
          <ul className="plain">
            {report.missing_evidence.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </Section>
      ) : null}

      <Limitations items={report.limitations} />

      {report.citations.length > 0 ? (
        <Section id="citations" title="Documentation cited">
          <p className="refs">{report.citations.map((id) => chip('citation', id))}</p>
        </Section>
      ) : null}
    </>
  )
}

function Limitations({ items }: { items: string[] }) {
  if (items.length === 0) return null
  return (
    <Section id="limitations" title="Limitations">
      <ul className="plain">
        {items.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </Section>
  )
}
