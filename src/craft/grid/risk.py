"""Consequence-metric risk classification for CRAFT."""

from __future__ import annotations

import math
from dataclasses import dataclass

from craft.models import ConsequenceMetrics, RiskLevel


@dataclass(frozen=True)
class RiskThresholds:
    """Conservative thresholds for the first CRAFT risk-engine slice."""

    l2_max_line_loading_ratio: float = 0.85
    l3_max_line_loading_ratio: float = 0.95
    reject_max_line_loading_ratio: float = 1.20
    reject_new_overload_count: int = 3
    l2_redispatch_mw: float = 20.0
    l3_redispatch_mw: float = 50.0
    l3_topology_changed_substations: int = 3


DEFAULT_RISK_THRESHOLDS = RiskThresholds()


class RiskEngine:
    """Map physical consequence metrics to CRAFT risk levels."""

    def __init__(self, thresholds: RiskThresholds = DEFAULT_RISK_THRESHOLDS) -> None:
        self.thresholds = thresholds

    def evaluate(self, metrics: ConsequenceMetrics) -> RiskLevel:
        thresholds = self.thresholds

        if _has_invalid_numeric_metric(metrics):
            return RiskLevel.REJECT
        if not metrics.converged or metrics.islanding:
            return RiskLevel.REJECT
        if metrics.load_shed_mw > 0:
            return RiskLevel.REJECT
        if metrics.max_line_loading_ratio >= thresholds.reject_max_line_loading_ratio:
            return RiskLevel.REJECT
        if metrics.new_overload_count >= thresholds.reject_new_overload_count:
            return RiskLevel.REJECT

        if (
            metrics.max_line_loading_ratio >= thresholds.l3_max_line_loading_ratio
            or metrics.new_overload_count > 0
            or metrics.redispatch_mw >= thresholds.l3_redispatch_mw
            or metrics.disconnected_line_count > 0
            or metrics.topology_changed_substations >= thresholds.l3_topology_changed_substations
        ):
            return RiskLevel.L3

        if (
            metrics.max_line_loading_ratio >= thresholds.l2_max_line_loading_ratio
            or metrics.redispatch_mw >= thresholds.l2_redispatch_mw
            or metrics.topology_changed_substations > 0
        ):
            return RiskLevel.L2

        return RiskLevel.L1


DEFAULT_RISK_ENGINE = RiskEngine()


def evaluate_risk(metrics: ConsequenceMetrics) -> RiskLevel:
    """Evaluate consequence metrics with the default CRAFT risk thresholds."""
    return DEFAULT_RISK_ENGINE.evaluate(metrics)


def _has_invalid_numeric_metric(metrics: ConsequenceMetrics) -> bool:
    values = (
        metrics.max_line_loading_ratio,
        metrics.min_security_margin,
        metrics.load_shed_mw,
        metrics.redispatch_mw,
    )
    return any(not math.isfinite(value) for value in values)
