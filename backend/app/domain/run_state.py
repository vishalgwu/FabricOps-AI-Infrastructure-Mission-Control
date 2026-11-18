"""The run state machine (docs/guide/02_ARCHITECTURE.md section 6)."""
from app.core.errors import InvalidTransitionError
from app.schemas.common import TERMINAL_RUN_STATUSES, RunStatus

ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.CREATED: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.WAITING_APPROVAL,
            RunStatus.COMPLETE,
            RunStatus.ABSTAINED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.WAITING_APPROVAL: frozenset(
        {RunStatus.COMPLETE, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    # Terminal states have no outgoing transitions.
    **{s: frozenset() for s in TERMINAL_RUN_STATUSES},
}


def check_transition(current: RunStatus, target: RunStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        allowed = sorted(s.value for s in ALLOWED_TRANSITIONS[current]) or ["none (terminal state)"]
        raise InvalidTransitionError(
            f"cannot move a run from {current.value} to {target.value}; allowed: {', '.join(allowed)}"
        )
