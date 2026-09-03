"""Risk-adaptive role policy for the first CRAFT MVP."""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator
from typing_extensions import Self

from craft.models import CRAFTModel, RiskLevel, Role


class RiskPolicyRule(CRAFTModel):
    risk_level: RiskLevel
    required_roles: tuple[Role, ...]
    authorizable: bool = True

    @field_validator("required_roles")
    @classmethod
    def normalize_roles(cls, roles: tuple[Role, ...]) -> tuple[Role, ...]:
        return tuple(sorted(set(roles), key=lambda role: role.value))

    @model_validator(mode="after")
    def reject_level_has_no_authorization_path(self) -> Self:
        if self.risk_level == RiskLevel.REJECT and (self.authorizable or self.required_roles):
            raise ValueError("REJECT risk must not have an authorization path.")
        return self


class RiskPolicy(CRAFTModel):
    policy_id: str = "craft-demo-risk-policy"
    version: str = "0.1.0"
    rules: tuple[RiskPolicyRule, ...] = Field(
        default=(
            RiskPolicyRule(risk_level=RiskLevel.L1, required_roles=(Role.OPERATOR,)),
            RiskPolicyRule(
                risk_level=RiskLevel.L2,
                required_roles=(Role.OPERATOR, Role.DISPATCHER),
            ),
            RiskPolicyRule(
                risk_level=RiskLevel.L3,
                required_roles=(Role.OPERATOR, Role.DISPATCHER, Role.SAFETY_OFFICER),
            ),
            RiskPolicyRule(
                risk_level=RiskLevel.REJECT,
                required_roles=(),
                authorizable=False,
            ),
        )
    )

    @model_validator(mode="after")
    def validate_unique_levels(self) -> Self:
        levels = [rule.risk_level for rule in self.rules]
        if len(levels) != len(set(levels)):
            raise ValueError("Risk policy cannot contain duplicate risk levels.")
        return self

    @property
    def policy_digest(self) -> str:
        return self.digest()

    def rule_for(self, risk_level: RiskLevel) -> RiskPolicyRule:
        for rule in self.rules:
            if rule.risk_level == risk_level:
                return rule
        raise KeyError(f"No policy rule for risk level {risk_level.value}.")

    def required_roles_for(self, risk_level: RiskLevel) -> tuple[Role, ...]:
        rule = self.rule_for(risk_level)
        return rule.required_roles

    def is_authorizable(self, risk_level: RiskLevel) -> bool:
        return self.rule_for(risk_level).authorizable


DEFAULT_RISK_POLICY = RiskPolicy()
