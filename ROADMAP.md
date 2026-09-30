# Roadmap

AI Control Centre is being developed incrementally around explicit, testable control boundaries.

A roadmap item is not considered implemented until the corresponding code, tests, and verification are present.

## Phase 1 — Deterministic Foundation

Status: In progress

- Project lifecycle
- Goal lifecycle
- Task lifecycle
- Goal lifecycle reconciliation
- Persistent project state
- Validation
- Deterministic command behavior
- Unit test coverage for core lifecycle behavior

## Phase 2 — Readiness and Execution Boundaries

Status: Implemented

- Task readiness evaluation
- Explicit readiness reasons
- Execution admission
- Execution start boundary
- Execution request contract
- Execution outcome contract
- Execution outcome recording
- Execution target selection
- Execution adapter registry
- Execution adapter failure handling
- Execution outcome identity validation
- Execution coordination

This phase establishes the execution control boundary without introducing unrestricted execution capabilities.

## Phase 3 — Controlled Execution

Status: Planned

Potential future work:

- Concrete local execution adapters
- Explicit execution permissions
- Execution limits
- Execution timeouts
- Execution result validation
- Execution diagnostics
- Controlled failure recovery
- Stronger execution isolation

## Phase 4 — Validation and Recovery

Status: Planned

Potential future work:

- Post-execution validation
- Failure diagnosis
- Structured recovery decisions
- Controlled retry boundaries
- State consistency checks
- Improved execution observability

Recovery behavior must remain deterministic and bounded.
