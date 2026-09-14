# core/risk_engine.py
"""
Risk Engine — configurable, per-tenant risk scoring.
Weights and thresholds come from tenant configuration, not from code.
"""
from dataclasses import dataclass
from typing import Any

DEFAULT_WEIGHTS = {
    "overdue_days": 0.40,
    "economic_impact": 0.30,
    "legal_risk": 0.20,
    "recurrence": 0.10,
}

DEFAULT_THRESHOLDS = {
    "low": {"min": 0, "max": 30},
    "medium": {"min": 30, "max": 70},
    "high": {"min": 70, "max": 100},
}


@dataclass
class RiskScore:
    total: float
    level: str
    component_scores: dict[str, float]
    weights_used: dict[str, float]
    thresholds_used: dict[str, Any]
    component_reasons: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.component_reasons is None:
            self.component_reasons = {}

    def validate_consistency(self) -> None:
        """Raise if the stored total does not match a fresh recomputation from components."""
        recomputed = sum(
            self.component_scores.get(k, 0.0) * self.weights_used.get(k, 0.0)
            for k in self.weights_used
        )
        recomputed = round(min(max(recomputed, 0.0), 100.0), 2)
        if abs(recomputed - self.total) > 0.01:
            raise ValueError(
                f"RiskScore consistency check FAILED: "
                f"recomputed={recomputed:.2f} != stored total={self.total:.2f}. "
                f"Components: {self.component_scores}, Weights: {self.weights_used}"
            )

    def explain(self) -> str:
        """
        Return a human-readable formula derived exclusively from the stored
        component_scores and weights_used — no hardcoded values.
        """
        lines = ["  Internal formula (generated from RiskEngine output):"]
        terms: list[str] = []
        for var in self.weights_used:
            raw = self.component_scores.get(var, 0.0)
            weight = self.weights_used[var]
            contribution = raw * weight
            reason = self.component_reasons.get(var, "")
            reason_str = f"  ← {reason}" if reason else ""
            lines.append(
                f"    {var:<22} {raw:5.1f} x {weight:.2f} = {contribution:5.2f}{reason_str}"
            )
            terms.append(f"{raw:.1f}*{weight:.2f}")
        lines.append("")
        lines.append(f"    total = {' + '.join(terms)}")
        lines.append(f"          = {self.total:.2f}  → {self.level}")
        return "\n".join(lines)


class RiskEngine:
    """
    Computes a 0–100 risk score from case variables.

    Configuration is loaded per tenant from TenantConfiguration:
        - risk_weights: dict of variable → weight (must sum to 1.0)
        - risk_thresholds: dict of level → {min, max}
    """

    def compute(
        self,
        overdue_days: int,
        overdue_amount: float,
        monthly_rent: float,
        has_legal_action: bool,
        previous_overdue_count: int,
        tenant_config: dict[str, Any],
    ) -> RiskScore:
        weights = tenant_config.get("risk_weights", DEFAULT_WEIGHTS)
        thresholds = tenant_config.get("risk_thresholds", DEFAULT_THRESHOLDS)

        # Normalize weights to sum to 1.0
        total_weight = sum(weights.values())
        if total_weight == 0:
            weights = DEFAULT_WEIGHTS
            total_weight = 1.0
        normalized = {k: v / total_weight for k, v in weights.items()}

        # --- Component scores (each 0–100) ---
        components: dict[str, float] = {}
        reasons: dict[str, str] = {}

        # 1. Overdue days score
        components["overdue_days"] = self._score_overdue_days(overdue_days)
        reasons["overdue_days"] = self._reason_overdue_days(overdue_days)

        # 2. Economic impact score (ratio of overdue to monthly rent)
        ratio = overdue_amount / monthly_rent if monthly_rent > 0 else 0.0
        components["economic_impact"] = self._score_economic_impact(
            overdue_amount, monthly_rent
        )
        reasons["economic_impact"] = (
            f"overdue/rent = {overdue_amount:,.0f}/{monthly_rent:,.0f} = {ratio:.2f}x"
        )

        # 3. Legal risk score
        components["legal_risk"] = 100.0 if has_legal_action else 0.0
        reasons["legal_risk"] = (
            "active legal action" if has_legal_action else "no active legal action"
        )

        # 4. Recurrence score
        components["recurrence"] = self._score_recurrence(previous_overdue_count)
        reasons["recurrence"] = f"{previous_overdue_count} prior incident(s)"

        # Weighted total
        total = sum(
            components.get(k, 0) * normalized.get(k, 0) for k in normalized
        )
        total = round(min(max(total, 0), 100), 2)

        level = self._derive_level(total, thresholds)

        return RiskScore(
            total=total,
            level=level,
            component_scores=components,
            weights_used=normalized,
            thresholds_used=thresholds,
            component_reasons=reasons,
        )

    def _score_overdue_days(self, days: int) -> float:
        """Non-linear scoring of overdue days."""
        if days <= 0:
            return 0.0
        if days <= 15:
            return 20.0
        if days <= 30:
            return 40.0
        if days <= 60:
            return 65.0
        if days <= 90:
            return 85.0
        return 100.0

    def _reason_overdue_days(self, days: int) -> str:
        """Human-readable band label matching _score_overdue_days exactly."""
        if days <= 0:
            return f"{days}d → no overdue (band: <=0d)"
        if days <= 15:
            return f"{days}d → band <=15d"
        if days <= 30:
            return f"{days}d → band <=30d"
        if days <= 60:
            return f"{days}d → band <=60d"
        if days <= 90:
            return f"{days}d → band <=90d"
        return f"{days}d → band >90d (max)"

    def _score_economic_impact(self, overdue: float, monthly: float) -> float:
        if monthly <= 0:
            return 50.0
        ratio = overdue / monthly
        if ratio <= 0.5:
            return 20.0
        if ratio <= 1:
            return 40.0
        if ratio <= 2:
            return 60.0
        if ratio <= 3:
            return 80.0
        return 100.0

    def _score_recurrence(self, count: int) -> float:
        if count == 0:
            return 0.0
        if count == 1:
            return 30.0
        if count == 2:
            return 60.0
        return 100.0

    def _derive_level(self, score: float, thresholds: dict[str, Any]) -> str:
        for level, bounds in thresholds.items():
            if bounds["min"] <= score <= bounds["max"]:
                return level.upper()
        return "ALTO"
