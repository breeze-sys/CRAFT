# CRAFT Project Review

Source planning summary: https://chatgpt.com/s/t_6a95692e05ac81918e8c02daebcb5fa9

## Name Update

Use the following name consistently:

```text
CRAFT: Consequence-aware Risk-Adaptive Framework for Trusted Execution of AI-Driven Power Grid Agents
```

Recommended Chinese rendering:

```text
面向 AI 电网智能体可信执行的后果感知风险自适应框架
```

Note: because "Trusted Execution" may be confused with hardware TEE, the project materials should explicitly say that CRAFT is a trusted execution workflow, not a Trusted Execution Environment design.

## Innovation Assessment

The innovation claim is reasonable if it is framed narrowly:

1. Strong: `GridState + Action -> PhysicalConsequence -> AuthorizationStrength`.
2. Strong: PCC binds action, state, predicted consequence, policy and approval with cryptographic signatures.
3. Strong: `Approval -> StateDrift -> RiskReevaluation -> DynamicReAuthorization`.
4. Medium: separating the Agent from execution and putting a gateway before tools.
5. Support only: SM2 signatures, SM3 digests, nonce, expiry, replay cache, hash-chain audit, role-based approval.

Do not claim the following as standalone novelty:

1. Runtime authorization gateway for agents.
2. Digital-twin pre-execution checking.
3. Risk tiers plus multi-role approval.
4. Action hash, state hash, policy digest, token expiry or execution receipt.
5. "Crypto prevents prompt injection" as a broad claim.

The safer claim is:

```text
CRAFT does not rely on the LLM to be safe. It cryptographically binds each candidate control action to independently evaluated physical consequences, dynamically selects authorization strength from those consequences, and revalidates the authorization when grid-state drift changes execution-time risk.
```

## Feasibility Assessment

Feasible for a competition MVP, with these constraints:

1. Use a small Grid2Op environment first, especially `l2rpn_case14_sandbox` or `educ_case14_redisp`.
2. Keep actions narrow: query state, overloaded lines, redispatch, line disconnect/reconnect, simple topology change, optional load shedding.
3. Use a deterministic or rule-based Agent fallback so demo success does not depend on LLM stability.
4. Implement SM2/SM3 as application cryptography, not as a novel primitive.
5. Make the dashboard explain the authorization path clearly: proposed action, predicted consequence, risk level, required roles, signatures, revalidation result, execution receipt.

The main feasibility risks are Grid2Op installation friction, risk-function credibility, and over-expanding the crypto layer. The biggest project-management risk is trying to integrate PowerMCP, a real LLM tool chain, full PKI and a polished dashboard all at once.

## Recommended V1 Architecture

```text
User / Operator
  -> LLM or Scripted Agent
  -> CRAFT Gateway
     -> Action Normalizer
     -> Consequence Evaluator
     -> Risk Engine
     -> Policy Engine
     -> SM2 Approval Verifier
     -> Revalidation Engine
     -> Execution Ticket Issuer
  -> Execution Gateway
  -> Grid2Op
  -> Signed Execution Receipt
```

Key invariant:

```text
Agent never receives direct access to the execution interface.
```

## Source Check Notes

TwinGridShield is the closest related work: it already evaluates LLM grid-agent actions in a deterministic network twin before release, checks physical invariants, uses IEEE 14-bus style studies, and reports 0 unsafe releases under matched-model trials while noting model-mismatch risk.

IETF's OT Command Authority draft already covers signed command-authority envelopes for agent-originated OT control actions, including agent identity, human principal, human authorization evidence, risk class and audit records. Treat it as related standards context.

AgentROA already covers cryptographic policy envelopes, scope binding, per-hop attestation and execution receipts for AI-agent actions. Treat policy digests and execution receipts as engineering building blocks, not the core novelty.

Grid2Op supports realistic power-grid operation experimentation and includes small case14 environments, which makes the proposed MVP technically practical.

