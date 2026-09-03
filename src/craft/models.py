"""Core CRAFT protocol data models.

These models intentionally separate unsigned payload digests from signed envelope
digests so later SM2 verification can bind the exact action, PCC and policy.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator
from typing_extensions import Self

from craft.serialization import canonical_digest_hex, canonical_json

HexDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PrincipalId = Annotated[str, Field(min_length=1, max_length=128)]
NonEmptyString = Annotated[str, Field(min_length=1)]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def expires_in(minutes: int) -> datetime:
    return utc_now() + timedelta(minutes=minutes)


def new_uuid() -> str:
    return str(uuid4())


def new_nonce() -> str:
    return secrets.token_urlsafe(24)


class Role(str, Enum):
    AGENT = "agent"
    OPERATOR = "operator"
    DISPATCHER = "dispatcher"
    SAFETY_OFFICER = "safety_officer"
    CONSEQUENCE_EVALUATOR = "consequence_evaluator"
    GATEWAY = "gateway"


class RiskLevel(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    REJECT = "REJECT"


class ActionType(str, Enum):
    NOOP = "noop"
    REDISPATCH = "redispatch"
    DISCONNECT_LINE = "disconnect_line"
    RECONNECT_LINE = "reconnect_line"
    CHANGE_TOPOLOGY = "change_topology"
    SHED_LOAD = "shed_load"


class ExecutionDecision(str, Enum):
    ALLOW = "allow"
    REJECT = "reject"
    REQUIRE_REAUTHORIZATION = "require_reauthorization"


class CRAFTModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        use_enum_values=False,
    )

    def canonical_json(self) -> str:
        return canonical_json(self)

    def digest(self) -> str:
        return canonical_digest_hex(self)


class ActorIdentity(CRAFTModel):
    subject_id: PrincipalId
    role: Role
    display_name: str | None = None
    public_key_digest: HexDigest | None = None
    certificate_digest: HexDigest | None = None


class GridStateRef(CRAFTModel):
    env_name: NonEmptyString
    state_digest: HexDigest
    captured_at: datetime = Field(default_factory=utc_now)
    episode_id: str | None = None
    timestep: int | None = Field(default=None, ge=0)
    backend: str | None = None


class ActionRequest(CRAFTModel):
    action_id: str = Field(default_factory=new_uuid)
    requested_by: ActorIdentity
    action_type: ActionType
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    target_state: GridStateRef | None = None
    justification: str | None = None
    nonce: str = Field(default_factory=new_nonce)
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def action_digest(self) -> str:
        return self.digest()


class SimulatorInfo(CRAFTModel):
    name: str = "Grid2Op"
    env_name: NonEmptyString
    version: str
    backend: str | None = None
    test_mode: bool = False
    n_sub: int | None = Field(default=None, ge=0)
    n_line: int | None = Field(default=None, ge=0)
    n_gen: int | None = Field(default=None, ge=0)
    n_load: int | None = Field(default=None, ge=0)


class ConsequenceMetrics(CRAFTModel):
    max_line_loading_ratio: float = Field(ge=0)
    new_overload_count: int = Field(ge=0)
    min_security_margin: float
    converged: bool
    islanding: bool = False
    load_shed_mw: float = Field(default=0, ge=0)
    redispatch_mw: float = Field(default=0, ge=0)
    disconnected_line_count: int = Field(default=0, ge=0)
    topology_changed_substations: int = Field(default=0, ge=0)


class PhysicalConsequenceCertificate(CRAFTModel):
    pcc_id: str = Field(default_factory=new_uuid)
    state_digest: HexDigest
    action_digest: HexDigest
    predicted_state_digest: HexDigest
    metrics: ConsequenceMetrics
    risk_level: RiskLevel
    policy_digest: HexDigest
    simulator: SimulatorInfo
    evaluator_id: PrincipalId
    issued_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime = Field(default_factory=lambda: expires_in(5))
    evaluator_signature: str | None = None

    @model_validator(mode="after")
    def validate_validity_window(self) -> Self:
        if self.expires_at <= self.issued_at:
            raise ValueError("PCC expiry must be later than issue time.")
        return self

    def signing_payload(self) -> dict[str, JsonValue]:
        return self._payload_without("evaluator_signature")

    def signing_digest(self) -> str:
        return canonical_digest_hex(self.signing_payload())

    def certificate_digest(self) -> str:
        return self.digest()

    def _payload_without(self, field_name: str) -> dict[str, JsonValue]:
        payload = self.model_dump(mode="json", exclude={field_name})
        return dict(payload)


class Approval(CRAFTModel):
    approval_id: str = Field(default_factory=new_uuid)
    pcc_id: str
    action_digest: HexDigest
    pcc_digest: HexDigest
    policy_digest: HexDigest
    role: Role
    approver_id: PrincipalId
    nonce: str = Field(default_factory=new_nonce)
    issued_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime = Field(default_factory=lambda: expires_in(10))
    signature_alg: str = "SM2-SM3"
    signature: str | None = None

    @model_validator(mode="after")
    def validate_validity_window(self) -> Self:
        if self.expires_at <= self.issued_at:
            raise ValueError("Approval expiry must be later than issue time.")
        return self

    def signing_payload(self) -> dict[str, JsonValue]:
        payload = self.model_dump(mode="json", exclude={"signature"})
        return dict(payload)

    def signing_digest(self) -> str:
        return canonical_digest_hex(self.signing_payload())

    def approval_digest(self) -> str:
        return self.digest()


class ApprovalSet(CRAFTModel):
    approval_set_id: str = Field(default_factory=new_uuid)
    pcc_id: str
    action_digest: HexDigest
    pcc_digest: HexDigest
    policy_digest: HexDigest
    required_roles: tuple[Role, ...]
    approvals: tuple[Approval, ...] = ()

    @field_validator("required_roles")
    @classmethod
    def normalize_required_roles(cls, roles: tuple[Role, ...]) -> tuple[Role, ...]:
        return tuple(sorted(set(roles), key=lambda role: role.value))

    @model_validator(mode="after")
    def validate_approval_consistency(self) -> Self:
        seen_roles: set[Role] = set()
        allowed_roles = set(self.required_roles)
        for approval in self.approvals:
            if approval.pcc_id != self.pcc_id:
                raise ValueError("Approval PCC id does not match approval set.")
            if approval.action_digest != self.action_digest:
                raise ValueError("Approval action digest does not match approval set.")
            if approval.pcc_digest != self.pcc_digest:
                raise ValueError("Approval PCC digest does not match approval set.")
            if approval.policy_digest != self.policy_digest:
                raise ValueError("Approval policy digest does not match approval set.")
            if approval.role not in allowed_roles:
                raise ValueError(f"Unexpected approval role: {approval.role.value}")
            if approval.role in seen_roles:
                raise ValueError(f"Duplicate approval role: {approval.role.value}")
            seen_roles.add(approval.role)
        return self

    @property
    def approved_roles(self) -> tuple[Role, ...]:
        roles = (approval.role for approval in self.approvals)
        return tuple(sorted(roles, key=lambda role: role.value))

    @property
    def missing_roles(self) -> tuple[Role, ...]:
        approved = set(self.approved_roles)
        return tuple(role for role in self.required_roles if role not in approved)

    def is_satisfied(self) -> bool:
        return not self.missing_roles


class ExecutionTicket(CRAFTModel):
    ticket_id: str = Field(default_factory=new_uuid)
    action_digest: HexDigest
    pcc_digest: HexDigest
    approval_set_digest: HexDigest
    risk_level: RiskLevel
    authorized_roles: tuple[Role, ...]
    decision: ExecutionDecision = ExecutionDecision.ALLOW
    issued_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime = Field(default_factory=lambda: expires_in(2))
    gateway_id: PrincipalId
    gateway_signature: str | None = None

    @field_validator("authorized_roles")
    @classmethod
    def normalize_authorized_roles(cls, roles: tuple[Role, ...]) -> tuple[Role, ...]:
        return tuple(sorted(set(roles), key=lambda role: role.value))

    @model_validator(mode="after")
    def validate_validity_window(self) -> Self:
        if self.expires_at <= self.issued_at:
            raise ValueError("Execution ticket expiry must be later than issue time.")
        return self

    def signing_payload(self) -> dict[str, JsonValue]:
        payload = self.model_dump(mode="json", exclude={"gateway_signature"})
        return dict(payload)

    def signing_digest(self) -> str:
        return canonical_digest_hex(self.signing_payload())


class ExecutionReceipt(CRAFTModel):
    receipt_id: str = Field(default_factory=new_uuid)
    ticket_id: str
    action_digest: HexDigest
    execution_state_digest: HexDigest
    result_state_digest: HexDigest | None = None
    executed_at: datetime = Field(default_factory=utc_now)
    success: bool
    reward: float | None = None
    done: bool | None = None
    error: str | None = None
    executor_id: PrincipalId
    receipt_signature: str | None = None

    def signing_payload(self) -> dict[str, JsonValue]:
        payload = self.model_dump(mode="json", exclude={"receipt_signature"})
        return dict(payload)

    def signing_digest(self) -> str:
        return canonical_digest_hex(self.signing_payload())


class AuditEvent(CRAFTModel):
    event_id: str = Field(default_factory=new_uuid)
    event_type: NonEmptyString
    actor_id: PrincipalId
    object_digests: dict[str, HexDigest] = Field(default_factory=dict)
    details: dict[str, JsonValue] = Field(default_factory=dict)
    previous_event_digest: HexDigest | None = None
    occurred_at: datetime = Field(default_factory=utc_now)
    event_signature: str | None = None

    def signing_payload(self) -> dict[str, JsonValue]:
        payload = self.model_dump(mode="json", exclude={"event_signature"})
        return dict(payload)

    def signing_digest(self) -> str:
        return canonical_digest_hex(self.signing_payload())
