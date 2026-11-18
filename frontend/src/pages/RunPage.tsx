import { useState } from 'react'
import { api } from '../api/client'
import type { Run } from '../api/types'
import { ErrorBox, Loading, Section, StatusBadge } from '../components/Common'
import { EvidenceTable } from '../components/EvidenceTable'
import { Inspector, type Selection } from '../components/Inspector'
import { ProposalPanel } from '../components/ProposalPanel'
import { ReportView } from '../components/ReportView'
import { Timeline } from '../components/Timeline'
import { failureReason, formatDuration, formatTime, isActive, isScriptedDemo } from '../format'
import { useLoad, useRunData, type RunData } from '../hooks'
import { links } from '../router'

export default function RunPage({ runId, pollActiveMs, pollWaitingMs }: { runId: string; pollActiveMs?: number; pollWaitingMs?: number }) {
  const { result, reload } = useRunData(runId, pollActiveMs, pollWaitingMs)
  const [selection, setSelection] = useState<Selection>(null)

  if (result.state === 'loading') return <Loading what="the run" />
  if (result.state === 'error') {
    return result.error.status === 404 ? (
      <div className="state state-error" role="alert">
        <p>No run with the ID <code>{runId}</code> exists.</p>
        <a href={links.history()}>Go to run history</a>
      </div>
    ) : (
      <ErrorBox error={result.error} onRetry={reload} />
    )
  }
  const { run, events, report, evidence, proposal } = result.data
  return (
    <div className={`run-layout${selection ? ' has-inspector' : ''}`}>
      <div className="run-main">
        <RunHeader run={run} />
        {isScriptedDemo(run.model_id) ? (
          <div className="callout callout-neutral" role="note">
            <strong>Scripted demo model.</strong> This analysis was written by a fixed script, not by an AI. It exists so
            the application can be shown without an API key. Everything else (evidence collection, validation, policy,
            approvals) is the real pipeline.
          </div>
        ) : null}
        <StatusExplanation data={result.data} />

        <Section id="timeline" title="What happened" hint="Each stage the investigation went through, in order.">
          <Timeline events={events} />
        </Section>

        {proposal ? <ProposalPanel key={proposal.proposal.id + proposal.proposal.version} view={proposal} onChanged={reload} /> : null}

        {report ? <ReportView report={report} selection={selection} onSelect={setSelection} /> : null}

        {!isActive(run.status) ? <EvidenceTable evidence={evidence} selection={selection} onSelect={setSelection} /> : null}
      </div>
      <Inspector selection={selection} evidence={evidence} onClose={() => setSelection(null)} />
    </div>
  )
}

function RunHeader({ run }: { run: Run }) {
  const { result } = useLoad((signal) => api.getIncident(run.incident_id, signal), run.incident_id)
  return (
    <header className="run-header">
      <h2>
        Investigation <code>{run.id}</code> <StatusBadge status={run.status} />
      </h2>
      <p>
        {result.state === 'ready' ? (
          <>
            Incident: <a href={links.incident(run.incident_id)}>{result.data.title}</a> ·{' '}
          </>
        ) : (
          <>
            Incident: <a href={links.incident(run.incident_id)}>{run.incident_id}</a> ·{' '}
          </>
        )}
        started {formatTime(run.started_at)}
        {run.finished_at ? <> · finished after {formatDuration(run.started_at, run.finished_at)}</> : null}
      </p>
      <p className="hint">
        {run.model_id ? (
          <>
            Model: {run.model_id} · prompt version {run.prompt_version ?? 'unknown'}
          </>
        ) : (
          'No model call was made for this run.'
        )}
      </p>
    </header>
  )
}

function StatusExplanation({ data }: { data: RunData }) {
  const { run, events, report } = data
  const failure = failureReason(events)
  switch (run.status) {
    case 'CREATED':
    case 'RUNNING':
      return (
        <div className="callout callout-progress" role="status">
          <strong>Investigation in progress.</strong> This page updates by itself.
        </div>
      )
    case 'WAITING_APPROVAL':
      return (
        <div className="callout callout-wait" role="status">
          <strong>Waiting for a human decision.</strong> The analysis is finished; the proposed next step below needs approval before anyone acts on it.
        </div>
      )
    case 'COMPLETE':
      return (
        <div className="callout callout-good">
          <strong>Complete.</strong> The report below is a set of hypotheses for a human to review, not a diagnosis.
        </div>
      )
    case 'ABSTAINED':
      return (
        <div className="callout callout-neutral">
          <strong>Abstained.</strong> The evidence was too stale, missing or thin to support any explanation, so none is offered.
          {report?.missing_evidence.length ? ' The list below says exactly what is needed.' : ''}
        </div>
      )
    case 'FAILED':
      return (
        <div className="callout callout-bad" role="alert">
          <strong>The investigation failed.</strong> Error code <code>{run.error_code ?? failure?.code ?? 'unknown'}</code>.
          {failure ? <p>{failure.message}</p> : null}
          <p className="hint">No conclusions were produced and nothing was changed.</p>
        </div>
      )
    case 'CANCELLED':
      return (
        <div className="callout callout-bad" role="status">
          <strong>Cancelled.</strong>{' '}
          {run.error_code === 'approval_expired'
            ? 'The proposed next step was not approved in time, so the run was closed.'
            : 'This run was cancelled before it finished.'}
        </div>
      )
  }
}
