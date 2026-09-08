"""Compatibility exports for the CRAFT security policy module."""

from craft.security.policy import (
    DEFAULT_RISK_POLICY,
    RiskPolicy,
    RiskPolicyRule,
    ensure_risk_is_authorizable,
    ensure_role_can_approve,
    required_roles_for_risk,
)

__all__ = [
    "DEFAULT_RISK_POLICY",
    "RiskPolicy",
    "RiskPolicyRule",
    "ensure_risk_is_authorizable",
    "ensure_role_can_approve",
    "required_roles_for_risk",
]
