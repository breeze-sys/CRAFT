import pytest

from craft.grid import evaluate_risk
from craft.models import ConsequenceMetrics, RiskLevel


def make_metrics(**overrides: object) -> ConsequenceMetrics:
    values = {
        "max_line_loading_ratio": 0.50,
        "new_overload_count": 0,
        "min_security_margin": 0.50,
        "converged": True,
    }
    values.update(overrides)
    return ConsequenceMetrics(**values)


@pytest.mark.parametrize(
    ("rho", "expected"),
    (
        (0.8499, RiskLevel.L1),
        (0.8500, RiskLevel.L2),
        (0.9499, RiskLevel.L2),
        (0.9500, RiskLevel.L3),
        (1.0100, RiskLevel.L3),
        (1.1999, RiskLevel.L3),
        (1.2000, RiskLevel.REJECT),
    ),
)
def test_line_loading_threshold_boundaries(rho: float, expected: RiskLevel) -> None:
    assert evaluate_risk(make_metrics(max_line_loading_ratio=rho)) == expected


@pytest.mark.parametrize(
    ("new_overloads", "expected"),
    (
        (0, RiskLevel.L1),
        (1, RiskLevel.L3),
        (2, RiskLevel.L3),
        (3, RiskLevel.REJECT),
    ),
)
def test_new_overload_count_threshold_boundaries(
    new_overloads: int,
    expected: RiskLevel,
) -> None:
    assert evaluate_risk(make_metrics(new_overload_count=new_overloads)) == expected


@pytest.mark.parametrize(
    ("override", "expected"),
    (
        ({"redispatch_mw": 19.999}, RiskLevel.L1),
        ({"redispatch_mw": 20.000}, RiskLevel.L2),
        ({"redispatch_mw": 50.000}, RiskLevel.L3),
        ({"topology_changed_substations": 1}, RiskLevel.L2),
        ({"topology_changed_substations": 3}, RiskLevel.L3),
        ({"disconnected_line_count": 1}, RiskLevel.L3),
    ),
)
def test_action_impact_threshold_boundaries(
    override: dict[str, object],
    expected: RiskLevel,
) -> None:
    assert evaluate_risk(make_metrics(**override)) == expected


@pytest.mark.parametrize(
    "override",
    (
        {"converged": False},
        {"islanding": True},
        {"load_shed_mw": 0.001},
        {"max_line_loading_ratio": float("inf")},
    ),
)
def test_hard_safety_failures_are_rejected(override: dict[str, object]) -> None:
    assert evaluate_risk(make_metrics(**override)) == RiskLevel.REJECT
