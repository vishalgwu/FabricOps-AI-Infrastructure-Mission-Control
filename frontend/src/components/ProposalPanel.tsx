import { useState } from 'react'
import { ApiError, api } from '../api/client'
import type { ProposalView } from '../api/types'
import { APPROVAL_LABELS, RISK_LABELS, formatTime, shortHash } from '../format'
import { toApiError } from '../hooks'
import { Section } from './Common'

const REVIEWER_KEY = 'fabricops.demoReviewer'

function savedReviewer(): string {
  try {
    return window.localStorage.getItem(REVIEWER_KEY) || 'demo-reviewer'
  } catch {
    return 'demo-reviewer'
  }
}

interface Props {
  view: ProposalView
  /** Called after a decision attempt so the page re-reads the backend's state. */
  onChanged: () => void
}

export function ProposalPanel({ view, onChanged }: Props) {
  const p = view.proposal
  const [reviewer, setReviewer] = useState(savedReviewer)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  const decide = async (decision: 'approved' | 'rejected') => {
    setBusy(true)
    setError(null)
    try {
      window.localStorage.setItem(REVIEWER_KEY, reviewer)
    } catch {
      /* storage may be unavailable; the name is only a convenience */
    }
    try {
      await api.decide(p.id, { decision, proposal_hash: p.proposal_hash, reason }, reviewer)
      setReason('')
      onChanged()
    } catch (err) {
      setError(toApiError(err))
      onChanged() // the backend is the source of truth: show what it actually has now
    } finally {
      setBusy(false)
    }
  }

  const canDecide = p.approval_status === 'pending'
  const ready = reason.trim().length > 0 && reviewer.trim().length > 0 && !busy

  return (
    <Section id="proposal" title="Proposed next step" hint="A suggestion for a human to review. FabricOps never runs it.">
      <p className="proposal-text">{p.description}</p>
      <dl className="facts">
        <dt>Target hosts</dt>
        <dd>{p.target_scope.join(', ')}</dd>
        <dt>Risk class</dt>
        <dd>
          <span className={`badge badge-risk-${p.risk_class}`}>{RISK_LABELS[p.risk_class]}</span>{' '}
          <span className="hint">set by backend policy, not by the model</span>
        </dd>
        <dt>Approval</dt>
        <dd>
          <span className={`badge badge-approval-${p.approval_status}`}>{APPROVAL_LABELS[p.approval_status]}</span>
        </dd>
        {p.expires_at ? (
          <>
            <dt>Decision window ends</dt>
            <dd>{formatTime(p.expires_at)}</dd>
          </>
        ) : null}
        <dt>Version</dt>
        <dd>
          {p.version} <span className="hint">fingerprint</span> <code title={p.proposal_hash}>{shortHash(p.proposal_hash)}</code>
        </dd>
      </dl>
      {p.policy_reasons.length > 0 ? (
        <details>
          <summary>Why this risk class</summary>
          <ul>
            {p.policy_reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </details>
      ) : null}
      <p className="notice">
        Nothing is executed. This system has no way to run a proposal. An approval or rejection only records a human
        decision.
      </p>

      {view.decision ? (
        <div className="decision" aria-label="Recorded decision">
          <strong>{view.decision.decision === 'approved' ? 'Approved' : 'Rejected'}</strong> by {view.decision.actor} at{' '}
          {formatTime(view.decision.created_at)}
          <p>Reason: {view.decision.reason}</p>
        </div>
      ) : null}
      {p.approval_status === 'expired' && !view.decision ? (
        <p className="state state-error" role="alert">
          The decision window closed without a decision, so this proposal can no longer be approved.
        </p>
      ) : null}

      {canDecide ? (
        <form
          className="decision-form"
          onSubmit={(e) => {
            e.preventDefault()
          }}
        >
          <h4>Review (demo)</h4>
          <p className="hint">
            The reviewer name is a demo stand-in sent as a request header. It is not real authentication; the backend
            decides who may approve.
          </p>
          <label>
            Demo reviewer
            <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
          </label>
          <label>
            Reason (required)
            <textarea value={reason} rows={2} onChange={(e) => setReason(e.target.value)} />
          </label>
          <div className="actions">
            <button type="button" disabled={!ready} onClick={() => void decide('approved')}>
              Approve
            </button>
            <button type="button" disabled={!ready} onClick={() => void decide('rejected')}>
              Reject
            </button>
          </div>
        </form>
      ) : null}
      {error ? (
        <p className="state state-error" role="alert">
          {error.status === 403 || error.status === 401
            ? `The backend refused this decision: ${error.message}`
            : error.code === 'proposal_changed'
              ? 'This proposal changed after you opened it. The page has reloaded the current version; review it again.'
              : error.message}
        </p>
      ) : null}
    </Section>
  )
}
