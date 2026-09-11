# Member B Grid Consequence Contract

This directory is the home for Member B's Grid2Op, consequence extraction,
risk-evaluation and execution-time revalidation work. It also contains the
contract consumed by Member A's security protocol layer.

## Current Files

```text
src/craft/grid/
  consequence.py  # evaluator protocol, result contract, mock evaluator
  evaluator.py    # Grid2Op step-result metrics extraction and evaluator adapter
  revalidation.py # approval-time vs execution-time risk comparison
  risk.py         # consequence-metric risk engine and thresholds
  README.md       # this handoff note
```

Member B's initial `origin/member2-risk-engine` work was reviewed and ported
into this package instead of keeping separate top-level modules. This keeps the
directory boundary clear:

```text
craft.grid.risk         -> risk rules
craft.grid.evaluator    -> Grid2Op observation/step metrics extraction
craft.grid.revalidation -> execution-time risk revalidation
craft.security          -> signatures, approvals, tickets and receipts
```

Do not put large datasets here. Grid2Op datasets stay under the ignored local
directory:

```text
data/grid2op
```

## Output Contract For Member B

Member B's real evaluator should implement:

```python
class ConsequenceEvaluator(Protocol):
    def evaluate(self, action: ActionRequest) -> ConsequenceEvaluationResult: ...
```

The returned `ConsequenceEvaluationResult` must provide:

1. `action_digest`: must equal `ActionRequest.action_digest`.
2. `state_digest`: SM3 digest of the current grid state snapshot used for simulation.
3. `predicted_state_digest`: SM3 digest of the predicted state after applying the action.
4. `metrics`: `ConsequenceMetrics` extracted from the simulator result.
5. `risk_level`: `RiskLevel.L1`, `L2`, `L3` or `REJECT`.
6. `simulator`: `SimulatorInfo` describing Grid2Op env/version/backend and grid size.

Member A will reject the result if `action_digest` does not match the exact
`ActionRequest`. This is the main boundary that prevents "evaluate one action,
execute another action" attacks.

## Required Metrics

At minimum, provide these fields in `ConsequenceMetrics`:

1. `max_line_loading_ratio`
2. `new_overload_count`
3. `min_security_margin`
4. `converged`
5. `islanding`
6. `load_shed_mw`
7. `redispatch_mw`
8. `disconnected_line_count`
9. `topology_changed_substations`

The first four fields are the most important for initial risk classification.
The remaining fields help explain why a decision became L2, L3 or REJECT.

## Suggested First Risk Rules

These are starting-point rules, not final research claims:

```text
REJECT if power flow does not converge
REJECT if islanding is true
REJECT if load shedding is not explicitly allowed
REJECT if max_line_loading_ratio is far above the hard safety bound
L3 if action is physically acceptable but close to a safety boundary
L2 if action changes dispatch/topology with moderate margin impact
L1 if action is low-impact and comfortably within margins
```

The report should emphasize that CRAFT's novelty is not the threshold formula
itself. The key idea is that real-time physical consequences become inputs to
cryptographic authorization.

## Mock Evaluator

Before real Grid2Op integration, use:

```python
from craft.grid import MockConsequenceEvaluator

evaluation = MockConsequenceEvaluator().evaluate(action)
```

Mock behavior is deterministic:

```text
noop                    -> L1
redispatch <= 10 MW     -> L1
redispatch <= 30 MW     -> L2
redispatch <= 60 MW     -> L3
redispatch > 60 MW      -> REJECT
reconnect_line          -> L2
disconnect_line         -> L3
change_topology         -> L3
shed_load               -> REJECT
```

Member B can replace the mock with a real Grid2Op evaluator while preserving the
same return type.

## Grid2Op Adapter

`Grid2OpConsequenceEvaluator` bridges a one-step Grid2Op simulation callback to
Member A's `ConsequenceEvaluator` contract:

```python
from craft.grid import Grid2OpConsequenceEvaluator, Grid2OpStepResult
from craft.models import SimulatorInfo


def simulate(action):
    return Grid2OpStepResult(
        obs_before=obs_before,
        obs_after=obs_after,
        done=done,
        info=info,
    )


evaluator = Grid2OpConsequenceEvaluator(
    simulate=simulate,
    simulator=SimulatorInfo(env_name="l2rpn_2019", version="1.12.5"),
)
evaluation = evaluator.evaluate(action)
```

Member B still needs to implement the real `simulate(action)` callback. It
should translate CRAFT `ActionRequest` parameters into Grid2Op actions, run a
copy/sandbox step, and return `obs_before`, `obs_after`, `done`, `reward` and
`info`. The adapter will then extract metrics, classify risk, and return a PCC
ready `ConsequenceEvaluationResult`.

## Risk Engine

The initial risk engine is intentionally conservative and threshold-based:

```text
REJECT if power flow does not converge, islanding/load shed occurs, rho >= 1.20,
       or at least 3 new overloads appear
L3     if rho >= 0.95, any new overload appears, a line is disconnected,
       redispatch >= 50 MW, or >= 3 substations change topology
L2     if rho >= 0.85, redispatch >= 20 MW, or any topology change appears
L1     otherwise
```

These rules are a first MVP policy, not a final power-systems claim. If Member B
changes thresholds later, update tests and report notes together so the
experimental story remains reproducible.

## Execution-Time Revalidation

`revalidate_execution(approval_pcc, execution_metrics)` compares the risk level
approved in the PCC with the risk level recomputed immediately before execution:

```text
execution risk <= approval risk -> allow
execution risk > approval risk  -> require_reauthorization
execution risk == REJECT        -> reject
```

Member A's `SecurityProtocol.consume_ticket_and_issue_receipt(...)` can now take
`execution_metrics`. If provided, the protocol checks revalidation before
consuming the one-time ticket or issuing a receipt.

```python
executed = protocol.consume_ticket_and_issue_receipt(
    ticketed,
    execution_state_digest=execution_state_digest,
    execution_metrics=execution_metrics,
    success=True,
)
```

If execution-time risk increases, the result uses a Dashboard-ready error code:

```text
revalidation_required
revalidation_rejected
```

## Contract Tests

Run these checks before and after replacing the mock:

```bash
conda run --no-capture-output -n craft python -m pytest tests/test_consequence_contract.py
conda run --no-capture-output -n craft python -m pytest tests/test_grid_risk.py
conda run --no-capture-output -n craft python -m pytest tests/test_grid_evaluator.py
conda run --no-capture-output -n craft python -m pytest tests/test_grid_revalidation.py
```

The contract test verifies:

1. The evaluator binds output to the exact action digest.
2. A mismatched action is rejected before PCC signing.
3. The evaluation result can be consumed by Member A's `issue_pcc(...)`.

The Member A demo also goes through this contract:

```bash
conda run --no-capture-output -n craft python scripts/demo_security_protocol.py
conda run --no-capture-output -n craft python scripts/demo_security_protocol.py --evaluator grid2op
```

## Member B Next Work

The reviewed branch is good enough as a risk/metrics core. The next larger
Member B task is not to duplicate these modules, but to provide the real
Grid2Op simulation callback behind `Grid2OpConsequenceEvaluator`:

1. Map `ActionRequest(action_type, parameters)` to valid Grid2Op actions.
2. Support at least `redispatch`, `disconnect_line`, `reconnect_line` and one
   topology-change path.
3. Run the action on a copied/sandboxed environment so evaluation does not
   mutate the live execution environment.
4. Return enough observation metadata to make `state_digest` and
   `predicted_state_digest` reproducible.
5. Build the two report scenarios: same action under different states produces
   different risk, and approval-time L2 becomes execution-time L3/REJECT so
   revalidation blocks or requires reauthorization.

### Required Action Parameter Contract

Use these `ActionRequest.parameters` conventions first. If Grid2Op requires a
different internal representation, translate inside the Grid2Op adapter and keep
the external CRAFT contract stable.

```text
redispatch
  required: gen_id, delta_mw
  example:  {"gen_id": 2, "delta_mw": -30.0}

disconnect_line
  required: line_id or line_ids
  example:  {"line_id": 3}

reconnect_line
  required: line_id or line_ids
  example:  {"line_ids": [3, 7]}

change_topology
  required: substation_id or substation_ids
  optional: topology_vector, bus, set_bus
  example:  {"substation_id": 4, "set_bus": {"load_1": 2}}
```

The adapter should reject unsupported or ambiguous parameters with a clear
exception before running simulation. CRAFT should not silently convert an
unknown action into noop.

### Required Simulator Behavior

The real callback passed to `Grid2OpConsequenceEvaluator` should:

1. Load the compact non-test dataset from `data/grid2op/l2rpn_2019` by default.
2. Use project-relative paths through existing dataset helpers; do not hardcode
   a teammate-specific home directory.
3. Run evaluation on a copied or sandboxed environment so simulated candidate
   actions do not mutate the live execution environment.
4. Return `Grid2OpStepResult(obs_before, obs_after, done, info, reward)`.
5. Include `scenario_id`, episode id and timestep in `state_digest` metadata
   when available.
6. Keep large Grid2Op datasets out of Git; only commit scripts, small configs
   and tests.

### Required Experiments For Report

Experiment 1: same action, different grid state.

```text
Input:  one fixed redispatch ActionRequest
State A: comfortable line margins
State B: near-overload line margins
Expected: evaluation A has lower RiskLevel than evaluation B
Output: action digest, state digests, metrics, risk levels
```

Experiment 2: approval-time risk drift before execution.

```text
Approval-time: PCC risk L2, Operator + Dispatcher approvals, Ticket issued
Execution-time case A: recomputed risk L3
Expected: SecurityProtocol returns revalidation_required and does not consume Ticket
Execution-time case B: recomputed risk REJECT
Expected: SecurityProtocol returns revalidation_rejected and does not issue Receipt
```

The current demo already has non-Grid2Op versions of these rejection paths:

```bash
conda run --no-capture-output -n craft python scripts/demo_security_protocol.py --scenario revalidation-upgrade
conda run --no-capture-output -n craft python scripts/demo_security_protocol.py --scenario revalidation-reject
```

Member A has also added a lightweight evidence collector. B can run it with the
mock evaluator for protocol-only evidence, or with `--evaluator grid2op` after
choosing a real Grid2Op state/action scenario:

```bash
conda run --no-capture-output -n craft make protocol-evidence
conda run --no-capture-output -n craft python scripts/collect_protocol_evidence.py --evaluator grid2op --scenarios happy-path --output artifacts/protocol/grid2op_happy_path.json
conda run --no-capture-output -n craft python scripts/demo_member2_grid2op_experiments.py --output artifacts/grid/member2_grid2op_report_experiments.json
```

### Evidence To Keep For Report

For every real Grid2Op experiment, save screenshots or terminal captures of:

1. The exact command used to run the experiment.
2. Dataset/env name, Grid2Op version, backend, episode id and timestep.
3. The fixed `ActionRequest.parameters` used in the scenario.
4. Before/after key metrics: max rho, new overload count, min security margin,
   convergence, islanding, load shed, redispatch amount and topology changes.
5. The resulting `RiskLevel` and required role set.
6. PCC digest, policy digest and action digest.
7. Revalidation result code when risk drifts: `revalidation_required` or
   `revalidation_rejected`.
8. A short note explaining why the state/action pair is meaningful for CRAFT.

Record these details in this README or `docs/member2-handoff.md` whenever B
changes experiment setup, thresholds, action mappings or dataset assumptions.
This keeps the report reproducible and avoids relying on screenshots alone.

### Suggested Member B Deliverables

Keep the package layout compact. Good candidate files:

```text
src/craft/grid/grid2op_actions.py     # ActionRequest -> Grid2Op action mapping
src/craft/grid/grid2op_simulator.py   # real simulation callback / env wrapper
tests/test_grid2op_actions.py         # pure unit tests for action mapping
tests/test_grid2op_simulator.py       # small fake-env or marked real-data tests
```

Acceptance checklist:

```bash
conda run -n craft python -m ruff check .
conda run -n craft python -m mypy src/craft
conda run -n craft python -m pytest
conda run --no-capture-output -n craft make check-grid-real
```

If real-data tests are slow or machine-dependent, mark them clearly and keep a
fake-env unit test path so CI and teammates can still validate the adapter logic
without re-downloading large data.
