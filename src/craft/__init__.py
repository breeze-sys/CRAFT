"""CRAFT project package."""

from craft.models import (
    ActionRequest,
    ActionType,
    ActorIdentity,
    Approval,
    ApprovalSet,
    AuditEvent,
    ConsequenceMetrics,
    ExecutionReceipt,
    ExecutionTicket,
    GridStateRef,
    PhysicalConsequenceCertificate,
    RiskLevel,
    Role,
    SimulatorInfo,
)
from craft.policy import DEFAULT_RISK_POLICY, RiskPolicy

PROJECT_NAME = "CRAFT"
PROJECT_FULL_NAME = (
    "Consequence-aware Risk-Adaptive Framework for Trusted Execution of "
    "AI-Driven Power Grid Agents"
)
__version__ = "0.1.0"

__all__ = [
    "PROJECT_FULL_NAME",
    "PROJECT_NAME",
    "ActionRequest",
    "ActionType",
    "ActorIdentity",
    "Approval",
    "ApprovalSet",
    "AuditEvent",
    "ConsequenceMetrics",
    "DEFAULT_RISK_POLICY",
    "ExecutionReceipt",
    "ExecutionTicket",
    "GridStateRef",
    "PhysicalConsequenceCertificate",
    "RiskLevel",
    "RiskPolicy",
    "Role",
    "SimulatorInfo",
    "__version__",
]
