"""SM2/SM3 helpers and role credentials for the CRAFT protocol layer."""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Annotated

from gmssl import sm2  # type: ignore[import-untyped]
from pydantic import Field, field_validator, model_validator
from typing_extensions import Self

from craft.models import ActorIdentity, CRAFTModel, Role
from craft.serialization import canonical_digest_hex, sm3_digest_hex

HexPrivateKey = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
HexPublicKey = Annotated[str, Field(pattern=r"^[0-9a-f]{128}$")]
HexSignature = Annotated[str, Field(pattern=r"^[0-9a-f]{128}$")]


def _normalize_hex(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Hex value must be a string.")
    return value.lower().removeprefix("0x")


def normalize_private_key(value: object) -> str:
    return _normalize_hex(value)


def normalize_public_key(value: object) -> str:
    public_key = _normalize_hex(value)
    if len(public_key) == 130 and public_key.startswith("04"):
        return public_key[2:]
    return public_key


def normalize_signature(value: object) -> str:
    return _normalize_hex(value)


def normalize_digest(value: object) -> str:
    digest = _normalize_hex(value)
    if len(digest) != 64:
        raise ValueError("SM3 digest must be 64 hex characters.")
    int(digest, 16)
    return digest


class SM2KeyPair(CRAFTModel):
    """Demo key pair used by tests and local protocol runs.

    Real deployments should load role keys from a managed keystore instead of
    generating them in process.
    """

    private_key: HexPrivateKey
    public_key: HexPublicKey

    @field_validator("private_key", mode="before")
    @classmethod
    def normalize_private(cls, value: object) -> str:
        return normalize_private_key(value)

    @field_validator("public_key", mode="before")
    @classmethod
    def normalize_public(cls, value: object) -> str:
        return normalize_public_key(value)


class TrustedPrincipal(CRAFTModel):
    """Public identity material trusted by CRAFT verifiers."""

    identity: ActorIdentity
    public_key: HexPublicKey

    @field_validator("public_key", mode="before")
    @classmethod
    def normalize_public(cls, value: object) -> str:
        return normalize_public_key(value)

    @model_validator(mode="after")
    def validate_public_key_digest(self) -> Self:
        expected = public_key_digest(self.public_key)
        if (
            self.identity.public_key_digest is not None
            and self.identity.public_key_digest != expected
        ):
            raise ValueError("Actor identity public key digest does not match public key.")
        return self


class RoleCredential(CRAFTModel):
    """Private signing material bound to one protocol role."""

    identity: ActorIdentity
    key_pair: SM2KeyPair

    @model_validator(mode="after")
    def validate_public_key_digest(self) -> Self:
        expected = public_key_digest(self.key_pair.public_key)
        if (
            self.identity.public_key_digest is not None
            and self.identity.public_key_digest != expected
        ):
            raise ValueError("Actor identity public key digest does not match key pair.")
        return self

    @property
    def subject_id(self) -> str:
        return self.identity.subject_id

    @property
    def role(self) -> Role:
        return self.identity.role

    @property
    def public_identity(self) -> ActorIdentity:
        return self.identity.model_copy(
            update={"public_key_digest": public_key_digest(self.key_pair.public_key)}
        )

    @property
    def public_principal(self) -> TrustedPrincipal:
        return TrustedPrincipal(identity=self.public_identity, public_key=self.key_pair.public_key)


class PrincipalRegistry:
    """In-memory public-key registry used by the MVP verifier path."""

    def __init__(self, principals: Iterable[TrustedPrincipal]) -> None:
        self._principals: dict[str, TrustedPrincipal] = {}
        for principal in principals:
            subject_id = principal.identity.subject_id
            if subject_id in self._principals:
                raise ValueError(f"Duplicate principal id: {subject_id}")
            self._principals[subject_id] = principal

    @classmethod
    def from_credentials(cls, credentials: Iterable[RoleCredential]) -> PrincipalRegistry:
        return cls(credential.public_principal for credential in credentials)

    def get(self, subject_id: str) -> TrustedPrincipal | None:
        return self._principals.get(subject_id)

    def require(self, subject_id: str) -> TrustedPrincipal:
        principal = self.get(subject_id)
        if principal is None:
            raise KeyError(f"Unknown principal id: {subject_id}")
        return principal

    def has_role(self, subject_id: str, role: Role) -> bool:
        principal = self.get(subject_id)
        return principal is not None and principal.identity.role == role

    @property
    def principals(self) -> dict[str, TrustedPrincipal]:
        return dict(self._principals)


def _curve_order() -> int:
    return int(sm2.default_ecc_table["n"], 16)


def random_scalar_hex() -> str:
    return f"{secrets.randbelow(_curve_order() - 1) + 1:064x}"


def derive_sm2_public_key(private_key: str) -> str:
    private_key = normalize_private_key(private_key)
    signer = sm2.CryptSM2(private_key=private_key, public_key="")
    public_key = signer._kg(int(private_key, 16), sm2.default_ecc_table["g"])
    if public_key is None:
        raise ValueError("Could not derive SM2 public key.")
    return normalize_public_key(public_key)


def generate_sm2_keypair() -> SM2KeyPair:
    private_key = random_scalar_hex()
    return SM2KeyPair(private_key=private_key, public_key=derive_sm2_public_key(private_key))


def public_key_digest(public_key: str) -> str:
    return sm3_digest_hex(bytes.fromhex(normalize_public_key(public_key)))


def sign_digest_hex(digest_hex: str, key_pair: SM2KeyPair) -> str:
    digest_hex = normalize_digest(digest_hex)
    signer = sm2.CryptSM2(private_key=key_pair.private_key, public_key=key_pair.public_key)
    for _ in range(32):
        signature = signer.sign(bytes.fromhex(digest_hex), random_scalar_hex())
        if signature is not None:
            signature = normalize_signature(signature)
            if verify_digest_hex(digest_hex, signature, key_pair.public_key):
                return signature
    raise RuntimeError("SM2 signing failed after multiple random nonce attempts.")


def verify_digest_hex(digest_hex: str, signature: str, public_key: str) -> bool:
    try:
        digest_hex = normalize_digest(digest_hex)
        signature = normalize_signature(signature)
        public_key = normalize_public_key(public_key)
        verifier = sm2.CryptSM2(private_key="", public_key="")
        # gmssl strips any public key starting with "04" in __init__, even when
        # those bytes are part of the x-coordinate. Assign after init to avoid it.
        verifier.public_key = public_key
        return bool(verifier.verify(signature, bytes.fromhex(digest_hex)))
    except Exception:
        return False


def sign_payload(payload: object, key_pair: SM2KeyPair) -> str:
    return sign_digest_hex(canonical_digest_hex(payload), key_pair)


def verify_payload(payload: object, signature: str, public_key: str) -> bool:
    return verify_digest_hex(canonical_digest_hex(payload), signature, public_key)


def create_role_credential(
    *,
    subject_id: str,
    role: Role,
    display_name: str | None = None,
    key_pair: SM2KeyPair | None = None,
) -> RoleCredential:
    key_pair = key_pair or generate_sm2_keypair()
    identity = ActorIdentity(
        subject_id=subject_id,
        role=role,
        display_name=display_name,
        public_key_digest=public_key_digest(key_pair.public_key),
    )
    return RoleCredential(identity=identity, key_pair=key_pair)


def create_operator_credential(subject_id: str = "operator-1") -> RoleCredential:
    return create_role_credential(
        subject_id=subject_id,
        role=Role.OPERATOR,
        display_name="Operator",
    )


def create_dispatcher_credential(subject_id: str = "dispatcher-1") -> RoleCredential:
    return create_role_credential(
        subject_id=subject_id,
        role=Role.DISPATCHER,
        display_name="Dispatcher",
    )


def create_safety_officer_credential(subject_id: str = "safety-officer-1") -> RoleCredential:
    return create_role_credential(
        subject_id=subject_id,
        role=Role.SAFETY_OFFICER,
        display_name="Safety Officer",
    )


def create_evaluator_credential(subject_id: str = "evaluator-1") -> RoleCredential:
    return create_role_credential(
        subject_id=subject_id,
        role=Role.CONSEQUENCE_EVALUATOR,
        display_name="Consequence Evaluator",
    )


def create_gateway_credential(subject_id: str = "gateway-1") -> RoleCredential:
    return create_role_credential(subject_id=subject_id, role=Role.GATEWAY, display_name="Gateway")


def create_demo_credentials() -> dict[Role, RoleCredential]:
    return {
        Role.OPERATOR: create_operator_credential(),
        Role.DISPATCHER: create_dispatcher_credential(),
        Role.SAFETY_OFFICER: create_safety_officer_credential(),
        Role.CONSEQUENCE_EVALUATOR: create_evaluator_credential(),
        Role.GATEWAY: create_gateway_credential(),
    }


def is_within_validity_window(
    issued_at: datetime,
    expires_at: datetime,
    *,
    at: datetime | None = None,
) -> bool:
    checked_at = _as_utc(at or datetime.now(timezone.utc))
    return _as_utc(issued_at) <= checked_at <= _as_utc(expires_at)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
