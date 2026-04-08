# core/case_state_machine.py
"""
Case State Machine — valid transitions only. Raises on invalid state changes.
"""
from enum import Enum
from typing import Optional


class CaseStatus(str, Enum):
    NEW = "NEW"
    IN_REVIEW = "IN_REVIEW"
    DECISION_GENERATED = "DECISION_GENERATED"
    HUMAN_OVERRIDE = "HUMAN_OVERRIDE"
    IN_EXECUTION = "IN_EXECUTION"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


# Adjacency map: current_state → set of allowed next states
VALID_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.NEW: {
        CaseStatus.IN_REVIEW,
        CaseStatus.CLOSED,  # e.g. duplicate case
    },
    CaseStatus.IN_REVIEW: {
        CaseStatus.DECISION_GENERATED,
        CaseStatus.ESCALATED,
        CaseStatus.CLOSED,
    },
    CaseStatus.DECISION_GENERATED: {
        CaseStatus.IN_EXECUTION,
        CaseStatus.HUMAN_OVERRIDE,
        CaseStatus.ESCALATED,
    },
    CaseStatus.HUMAN_OVERRIDE: {
        CaseStatus.IN_EXECUTION,
        CaseStatus.ESCALATED,
        CaseStatus.CLOSED,
    },
    CaseStatus.IN_EXECUTION: {
        CaseStatus.CLOSED,
        CaseStatus.ESCALATED,
    },
    CaseStatus.ESCALATED: {
        CaseStatus.IN_EXECUTION,
        CaseStatus.CLOSED,
        CaseStatus.DECISION_GENERATED,
    },
    CaseStatus.CLOSED: set(),  # terminal state
}


class InvalidTransitionError(Exception):
    def __init__(self, current: CaseStatus, target: CaseStatus) -> None:
        super().__init__(
            f"Invalid state transition: {current.value} → {target.value}. "
            f"Allowed from {current.value}: {[s.value for s in VALID_TRANSITIONS[current]]}"
        )
        self.current = current
        self.target = target


class CaseStateMachine:
    """
    Validates and executes state transitions.
    Does NOT persist — call repository after transition.
    """

    def transition(
        self,
        current_status: str,
        target_status: str,
        *,
        actor: Optional[str] = None,
    ) -> CaseStatus:
        """
        Attempt a transition. Returns new status if valid, raises if not.
        """
        current = CaseStatus(current_status)
        target = CaseStatus(target_status)

        allowed = VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidTransitionError(current, target)

        return target

    def can_transition(self, current_status: str, target_status: str) -> bool:
        """Non-raising check."""
        try:
            self.transition(current_status, target_status)
            return True
        except (InvalidTransitionError, ValueError):
            return False

    def get_allowed_transitions(self, current_status: str) -> list[str]:
        current = CaseStatus(current_status)
        return [s.value for s in VALID_TRANSITIONS.get(current, set())]
