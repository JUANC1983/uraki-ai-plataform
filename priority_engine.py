# core/priority_engine.py
"""
Priority Engine — scores and classifies case urgency.

Priority = f(risk_score, escalation_required, overdue_days, legal_flag)

Thresholds are configurable per tenant via TenantConfig.priority_thresholds.
"""
from dataclasses import dataclass
from typing import Any, Optional

from core.decision_contract import CasePriority


@dataclass
class PriorityResult:
    priority: CasePriority
    score: float          # 0–100 composite priority score
    factors: dict[str, float]  # contribution of each input factor


class PriorityEngine:
    """
    Deterministic, configurable priority scorer.

    Algorithm:
        base_score    = risk_score  (0–100, weight 0.50)
        overdue_score = f(overdue_days)  (0–100, weight 0.30)
        flag_bonus    = legal_flag * 20 + escalation_required * 10  (weight 0.20)

    Thresholds from TenantConfig:
        critical  ≥ config.critical  (default 85)
        high      ≥ config.high      (default 65)
        medium    ≥ config.medium    (default 40)
        low       < config.medium
    """

    # Default weights (sum to 1.0)
    _W_RISK = 0.50
    _W_OVERDUE = 0.30
    _W_FLAGS = 0.20

    def compute(
        self,
        *,
        risk_score: float,
        escalation_required: bool,
        overdue_days: int,
        legal_flag: bool,
        config_thresholds: "PriorityThresholds | None" = None,  # type: ignore[name-defined]
    ) -> PriorityResult:
        # Component scores (each 0–100)
        overdue_score = self._overdue_score(overdue_days)
        flag_score = self._flag_score(legal_flag=legal_flag, escalation=escalation_required)

        composite = (
            risk_score * self._W_RISK
            + overdue_score * self._W_OVERDUE
            + flag_score * self._W_FLAGS
        )
        composite = round(min(max(composite, 0), 100), 2)

        priority = self._classify(composite, config_thresholds)

        return PriorityResult(
            priority=priority,
            score=composite,
            factors={
                "risk_score_contribution": round(risk_score * self._W_RISK, 2),
                "overdue_contribution": round(overdue_score * self._W_OVERDUE, 2),
                "flag_contribution": round(flag_score * self._W_FLAGS, 2),
            },
        )

    # ------------------------------------------------------------------
    # Component scorers
    # ------------------------------------------------------------------

    def _overdue_score(self, days: int) -> float:
        if days <= 0:
            return 0.0
        if days <= 15:
            return 15.0
        if days <= 30:
            return 35.0
        if days <= 60:
            return 60.0
        if days <= 90:
            return 80.0
        if days <= 120:
            return 90.0
        return 100.0

    def _flag_score(self, *, legal_flag: bool, escalation: bool) -> float:
        score = 0.0
        if legal_flag:
            score += 60.0
        if escalation:
            score += 40.0
        return min(score, 100.0)

    def _classify(self, composite: float, thresholds: Optional[Any]) -> CasePriority:
        if thresholds is None:
            critical, high, medium = 85.0, 65.0, 40.0
        else:
            critical = thresholds.critical
            high = thresholds.high
            medium = thresholds.medium

        if composite >= critical:
            return CasePriority.CRITICAL
        if composite >= high:
            return CasePriority.HIGH
        if composite >= medium:
            return CasePriority.MEDIUM
        return CasePriority.LOW
