from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ImportanceFeedback


@dataclass(frozen=True)
class PolicyEvaluation:
    estimand: str
    observations: int
    effective_sample_size: float
    behavior_value: float | None
    doubly_robust_value: float | None
    standard_error: float | None
    ci_95: tuple[float, float] | None
    overlap_warning: bool
    status: str
    assumptions: tuple[str, ...]


def _target_probability(context: dict) -> float:
    base = float(context.get("base_score", 0.0))
    safety_bonus = 0.8 if context.get("risk_level") in {"critical", "high"} else 0.0
    logit = -1.0 + 0.22 * base + safety_bonus
    probability = 1.0 / (1.0 + math.exp(-logit))
    return max(0.05, min(0.95, probability))


def evaluate_shadow_policy(session: Session, clinic_id: str) -> PolicyEvaluation:
    records = list(
        session.scalars(select(ImportanceFeedback).where(ImportanceFeedback.clinic_id == clinic_id))
    )
    assumptions = (
        "Consistency between logged and evaluated ranking interactions",
        "No unmeasured confounding conditional on the logged context",
        "Positive behavior propensity wherever the shadow policy assigns probability",
        "Correct behavior propensities or adequate outcome-model approximation",
    )
    if not records:
        return PolicyEvaluation(
            estimand=(
                "Expected accepted/relevant highlight feedback under the shadow display policy"
            ),
            observations=0,
            effective_sample_size=0.0,
            behavior_value=None,
            doubly_robust_value=None,
            standard_error=None,
            ci_95=None,
            overlap_warning=True,
            status="insufficient_data",
            assumptions=assumptions,
        )

    rewards = [item.reward for item in records]
    outcome_mean = sum(rewards) / len(rewards)
    weights: list[float] = []
    contributions: list[float] = []
    for item in records:
        weight = _target_probability(item.context) / max(0.01, item.display_propensity)
        weights.append(weight)
        contributions.append(outcome_mean + weight * (item.reward - outcome_mean))
    estimate = sum(contributions) / len(contributions)
    if len(contributions) > 1:
        variance = sum((value - estimate) ** 2 for value in contributions) / (
            len(contributions) - 1
        )
        standard_error = math.sqrt(variance / len(contributions))
    else:
        standard_error = 0.0
    effective_sample_size = (sum(weights) ** 2) / max(1e-12, sum(w**2 for w in weights))
    overlap_warning = effective_sample_size < max(5.0, 0.25 * len(records)) or max(weights) > 10
    lower = max(0.0, estimate - 1.96 * standard_error)
    upper = min(1.0, estimate + 1.96 * standard_error)
    status = "exploratory" if len(records) < 50 or overlap_warning else "shadow_evaluable"
    return PolicyEvaluation(
        estimand="Expected accepted/relevant highlight feedback under the shadow display policy",
        observations=len(records),
        effective_sample_size=round(effective_sample_size, 3),
        behavior_value=round(outcome_mean, 4),
        doubly_robust_value=round(estimate, 4),
        standard_error=round(standard_error, 4),
        ci_95=(round(lower, 4), round(upper, 4)),
        overlap_warning=overlap_warning,
        status=status,
        assumptions=assumptions,
    )
