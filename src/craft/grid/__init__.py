"""Grid-facing contracts and adapters for CRAFT."""

from craft.grid.consequence import (
    ConsequenceEvaluationResult,
    ConsequenceEvaluator,
    MockConsequenceEvaluator,
)
from craft.grid.evaluator import (
    Grid2OpConsequenceEvaluator,
    Grid2OpStepResult,
    Grid2OpStepSimulator,
    evaluate_consequence_risk,
    extract_consequence_metrics,
    observation_digest,
)
from craft.grid.grid2op_actions import (
    Grid2OpActionError,
    action_request_to_grid2op_action,
    action_request_to_grid2op_payload,
)
from craft.grid.grid2op_simulator import (
    CRAFT_GRID2OP_METADATA_KEY,
    Grid2OpSimulationError,
    Grid2OpSimulator,
    Grid2OpSimulatorConfig,
    make_grid2op_consequence_evaluator,
    make_grid2op_env,
    simulator_info_from_env,
    state_digest_metadata,
)
from craft.grid.revalidation import (
    RISK_LEVEL_ORDER,
    RevalidationResult,
    decide_revalidation,
    revalidate_execution,
    risk_level_rank,
)
from craft.grid.risk import (
    DEFAULT_RISK_ENGINE,
    DEFAULT_RISK_THRESHOLDS,
    RiskEngine,
    RiskThresholds,
    evaluate_risk,
)

__all__ = [
    "DEFAULT_RISK_ENGINE",
    "DEFAULT_RISK_THRESHOLDS",
    "ConsequenceEvaluationResult",
    "ConsequenceEvaluator",
    "Grid2OpConsequenceEvaluator",
    "Grid2OpActionError",
    "Grid2OpSimulationError",
    "Grid2OpSimulator",
    "Grid2OpSimulatorConfig",
    "Grid2OpStepResult",
    "Grid2OpStepSimulator",
    "MockConsequenceEvaluator",
    "RISK_LEVEL_ORDER",
    "RevalidationResult",
    "RiskEngine",
    "RiskThresholds",
    "action_request_to_grid2op_action",
    "action_request_to_grid2op_payload",
    "CRAFT_GRID2OP_METADATA_KEY",
    "decide_revalidation",
    "evaluate_consequence_risk",
    "evaluate_risk",
    "extract_consequence_metrics",
    "make_grid2op_consequence_evaluator",
    "make_grid2op_env",
    "observation_digest",
    "revalidate_execution",
    "risk_level_rank",
    "simulator_info_from_env",
    "state_digest_metadata",
]
