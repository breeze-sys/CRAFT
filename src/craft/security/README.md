# Member A Security Protocol Layer

This directory contains the Member A implementation scope:

```text
SM2/SM3
PCC
Approval
ExecutionTicket
Receipt
Role policy
Security verification tests
```

Root `README.md` should stay focused on project introduction. This file records
the concrete security protocol work so Member B and Member C can integrate with
it without guessing module boundaries.

## Responsibility Boundary

Member A owns:

1. SM3 canonical digest and SM2 signing/verification wrappers.
2. Role identities for Operator, Dispatcher and Safety Officer.
3. Consequence-bound PCC signing and verification.
4. Risk-level to required-role policy: L1, L2, L3 and REJECT.
5. Approval signatures bound to action digest, PCC digest and policy digest.
6. Execution Ticket issuing, verification and one-time replay protection.
7. Execution Receipt issuing and verification.
8. Structured verification results for Dashboard failure explanations.
9. Signed hash-chain audit events and protocol transcript export.
10. Security tests for action tampering, ticket replay and role impersonation.

Member A does not own:

1. Grid2Op consequence simulation internals.
2. Risk metric extraction from real grid observations.
3. LLM Agent prompts, tool calling, dashboard UI or end-to-end demo routing.

Those parts belong to Member B and Member C, but they should call the security
interfaces here instead of reimplementing signing or policy logic.

## Directory Layout

```text
src/craft/security/
  audit.py       # signed hash-chain audit events and protocol transcript export
  crypto.py      # SM2/SM3 wrappers, role credentials, public principal registry
  errors.py      # VerificationResult and protocol error codes for UI/API use
  pcc.py         # Physical Consequence Certificate issuing and verification
  approval.py    # user approval signing and approval-set verification
  policy.py      # L1/L2/L3/REJECT role policy
  protocol.py    # high-level protocol facade for Gateway and demos
  ticket.py      # Execution Ticket issuing, verification and replay cache
  receipt.py     # signed execution receipt issuing and verification
  README.md      # this handoff note
```

Shared Pydantic data contracts currently live in:

```text
src/craft/models.py
```

The old import path `craft.policy` is kept as a compatibility export for now.
New code should prefer `craft.security.policy`.

## Core Flow

The intended protocol path is:

```text
ActionRequest
  -> ConsequenceEvaluator.evaluate(...)
  -> issue_pcc(...)
  -> verify_pcc_for_action(...)
  -> create_approval(...) for each required role
  -> build_approval_set(...)
  -> verify_approval_set(...)
  -> issue_execution_ticket(...)
  -> revalidate_execution(...) if execution-time metrics are available
  -> consume_execution_ticket(...)
  -> issue_execution_receipt(...)
  -> verify_execution_receipt(...)
  -> build_audit_chain(...)
  -> build_transcript(...)
```

For integration work, prefer the high-level facade in `protocol.py`:

```python
from craft.security import create_demo_security_protocol

protocol = create_demo_security_protocol()
certified = protocol.certify_action(action)
authorized = protocol.approve_action(certified)
ticketed = protocol.issue_ticket(authorized)
executed = protocol.consume_ticket_and_issue_receipt(
    ticketed,
    execution_state_digest=state_digest,
    execution_metrics=execution_metrics,
    result_state_digest=result_state_digest,
    success=True,
)
```

`execution_metrics` is optional for early demos. When Member B provides real
Grid2Op execution-time metrics, pass it here so the protocol can block execution
before Ticket consumption if risk increased after approval.

The facade exposes these protocol stages:

```text
CertifiedAction  -> action + evaluator output digest + signed PCC
AuthorizedAction -> certified action + ApprovalSet + verification result
TicketedAction   -> authorized action + ExecutionTicket + verification result
ExecutedAction   -> ticket consumption + Receipt + receipt verification
```

It can also export audit material after a run:

```python
audit_chain = protocol.build_audit_chain(
    certified=certified,
    authorized=authorized,
    ticketed=ticketed,
    executed=executed,
)
transcript = protocol.build_transcript(
    certified=certified,
    authorized=authorized,
    ticketed=ticketed,
    executed=executed,
    audit_chain=audit_chain,
)
transcript_json = transcript.export_json()
```

If Member B provides a real Grid2Op evaluator implementing
`ConsequenceEvaluator`, it can be injected without changing the security flow:

```python
protocol = SecurityProtocol(
    evaluator=real_grid2op_evaluator,
    credentials=credentials,
    policy=DEFAULT_RISK_POLICY,
)
```

Boolean `verify_*` functions are kept for tests and simple guards. Dashboard and
Gateway code should prefer the matching `explain_*` functions when a failure
reason is needed:

```python
result = explain_execution_ticket(
    ticket,
    gateway_public_principal,
    action=action,
    pcc=pcc,
    approval_set=approval_set,
    policy=DEFAULT_RISK_POLICY,
    replay_cache=replay_cache,
)

if not result.valid:
    print(result.code.value, result.message, result.details)
```

Run the current happy-path demo from the repository root:

```bash
conda run --no-capture-output -n craft python scripts/demo_security_protocol.py
```

The demo uses deterministic mock consequence values. It does not call Grid2Op directly:
Member B can later replace `MockConsequenceEvaluator` with a real Grid2Op
evaluator while keeping the same Member A protocol calls.

To run the same security protocol path with Member B's real Grid2Op simulator
callback and local `l2rpn_2019` data:

```bash
conda run --no-capture-output -n craft python scripts/demo_security_protocol.py --evaluator grid2op
```

Attack and rejection scenarios:

```bash
conda run --no-capture-output -n craft python scripts/demo_security_protocol.py --scenario tamper-action
conda run --no-capture-output -n craft python scripts/demo_security_protocol.py --scenario replay-ticket
conda run --no-capture-output -n craft python scripts/demo_security_protocol.py --scenario wrong-role
conda run --no-capture-output -n craft python scripts/demo_security_protocol.py --scenario expired-pcc
conda run --no-capture-output -n craft python scripts/demo_security_protocol.py --scenario policy-mismatch
conda run --no-capture-output -n craft python scripts/demo_security_protocol.py --scenario missing-role
conda run --no-capture-output -n craft python scripts/demo_security_protocol.py --scenario tamper-receipt
conda run --no-capture-output -n craft python scripts/demo_security_protocol.py --scenario revalidation-upgrade
conda run --no-capture-output -n craft python scripts/demo_security_protocol.py --scenario revalidation-reject
```

Each attack scenario exits successfully when the expected rejection is observed.
This is intentional: the demo is proving that CRAFT rejects the unsafe or
invalid operation.

Expected rejection codes:

```text
tamper-action  -> action_digest_mismatch
replay-ticket  -> ticket_replay
wrong-role     -> role_mismatch
expired-pcc    -> expired
policy-mismatch -> policy_digest_mismatch
missing-role   -> missing_required_roles
tamper-receipt -> signature_invalid
revalidation-upgrade -> revalidation_required
revalidation-reject  -> revalidation_rejected
```

Important binding rules:

1. `ActionRequest.action_digest` binds action type, parameters, target state,
   requester, nonce and creation time.
2. PCC signatures bind `state_digest`, `action_digest`, predicted consequence,
   risk level, policy digest and simulator metadata.
3. Approval signatures bind the complete signed PCC digest, action digest,
   role, approver id, policy digest, nonce and expiry.
4. Execution Tickets bind the action, signed PCC, approval set and authorized
   role set.
5. Receipts bind the executed Ticket and result-state digest.

## Role Policy

Default policy:

```text
L1     -> Operator
L2     -> Operator + Dispatcher
L3     -> Operator + Dispatcher + Safety Officer
REJECT -> no authorization path
```

The implementation sorts roles deterministically before hashing so policy
digests remain stable across machines.

## Integration Notes

Member B should implement the contract in:

```text
src/craft/grid/consequence.py
```

Current bridge object:

```text
ConsequenceEvaluationResult
```

Member B should provide the following fields through that object:

1. `ActionRequest`
2. `action_digest`, which must equal `ActionRequest.action_digest`
3. `state_digest`
4. `predicted_state_digest`
5. `ConsequenceMetrics`
6. `RiskLevel`
7. `SimulatorInfo`

Member A then calls `evaluation.ensure_matches_action(action)` before
`issue_pcc(...)`. This check is intentionally strict: it prevents evaluating
one action and signing a PCC for another action.

For detailed Member B guidance, see:

```text
src/craft/grid/README.md
```

Before real Grid2Op integration, use:

```python
from craft.grid import MockConsequenceEvaluator

evaluation = MockConsequenceEvaluator().evaluate(action)
evaluation.ensure_matches_action(action)
```

Member C should treat `ExecutionTicket` as the only object that unlocks the
actual execution path. A replay cache must be checked before execution:

```python
cache = TicketReplayCache()
allowed = consume_execution_ticket(ticket, gateway_public_principal, cache)
```

If `allowed` is false, the gateway must not execute the action.

## Verification Results

All `explain_*` functions return:

```text
VerificationResult
  valid: bool
  code: ProtocolErrorCode
  message: str
  details: dict
```

Recommended Dashboard display:

```text
code     -> stable machine-readable reason
message  -> short human-readable explanation
details  -> object ids, expected digests, provided digests or missing roles
```

Common failure codes:

1. `signature_invalid`: signature does not verify against the registered public key.
2. `missing_signature`: PCC, Approval, Ticket or Receipt has no signature.
3. `expired`: PCC, Approval or Ticket is outside its validity window.
4. `action_digest_mismatch`: signed object is not bound to the submitted action.
5. `policy_digest_mismatch`: signed object was produced under a different policy.
6. `missing_required_roles`: ApprovalSet lacks at least one role required by policy.
7. `role_mismatch`: principal role does not match the signed role or required verifier role.
8. `unknown_principal`: approval references an approver not in the trusted registry.
9. `ticket_replay`: ExecutionTicket was already consumed.
10. `pcc_digest_mismatch`: approval or ticket is not bound to the signed PCC.
11. `audit_chain_mismatch`: audit events were deleted, reordered or relinked.
12. `revalidation_required`: execution-time risk exceeds the approved PCC risk.
13. `revalidation_rejected`: execution-time risk is physically unacceptable.

This lets Member C show precise rejection reasons such as "Ticket replay" or
"Missing Dispatcher approval" instead of a generic failure.

## Audit Chain And Transcript

`AuditChain` is an immutable signed hash chain. Each `AuditEvent` is signed by
the role that produced the event and stores the digest of the previous signed
event. This gives two useful properties for the MVP:

1. Editing an event breaks that event's SM2 signature.
2. Deleting or reordering events breaks the `previous_event_digest` chain link.

Current event types:

```text
pcc_issued
approval_signed
approval_set_verified
approval_rejected
ticket_issued
ticket_not_issued
execution_revalidated
ticket_consumed
ticket_not_consumed
receipt_issued
```

`ProtocolTranscript` is a compact JSON-exportable summary for reports and
Dashboard integration. It includes action/PCC/ApprovalSet/Ticket/Receipt
digests, risk level, role sets, verification results and audit event digests.

## Key Handling

`create_demo_credentials()` generates in-memory demo keys for local tests and
prototype demos. Do not commit private keys. Later, this should be replaced by a
small local keystore or configuration loader that remains outside Git.

The current MVP registry is:

```python
registry = PrincipalRegistry.from_credentials(credentials.values())
```

It is intentionally simple: subject id maps to role and public key. This is
enough for the first security tests, while leaving room for a future CA or role
certificate module.

Implementation note: `gmssl.CryptSM2` strips a leading `04` inside its
constructor because some callers pass uncompressed public keys with a `04`
prefix. A valid 128-hex-character x/y public key can also naturally start with
`04`, so `crypto.py` normalizes the key first and assigns it to the verifier
after construction. Keep this wrapper path instead of calling `gmssl` directly
from other modules.

## Design Extensions Worth Adding Later

Crypto-related depth should come from stronger protocol properties, not from
piling on many algorithms. Good next enhancements:

1. A small demo CA or role-certificate issuer for Operator, Dispatcher,
   SafetyOfficer, Evaluator and Gateway.
2. Durable replay storage so used ticket ids survive process restart.
3. Key loading from ignored local files instead of in-memory demo generation.
4. Revalidation binding: execution-time PCC must prove risk did not increase
   beyond the approved level before Ticket consumption. The first gate is now
   implemented with Member B metrics; a future enhancement can add a separately
   signed execution-time PCC.
5. Durable audit-chain storage and search for Dashboard filtering.
6. More formal threat-model notes mapping each attack to the exact digest or
   signature binding that blocks it.

## Acceptance Stages

Stage 1:

```text
Input ActionRequest -> generate signed PCC -> verify PCC signature and binding.
```

Stage 2:

```text
RiskLevel -> required role set -> verify correct approvals only.
```

Stage 3:

```text
Valid ApprovalSet -> issue one-time ExecutionTicket -> reject replay.
```

Security tests must cover:

1. Action parameter tampering.
2. Old Ticket replay.
3. Wrong-role impersonation.
