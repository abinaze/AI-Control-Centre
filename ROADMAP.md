# Roadmap

AI Control Centre is being developed incrementally around explicit, testable control boundaries.

A roadmap item is not considered implemented until the corresponding code, tests, and verification are present. The current verified state, including known gaps, is recorded in [docs/STATUS.md](docs/STATUS.md).

Status labels used below: **Implemented**, **Proposed**, **Planned**, **Research**. See [docs/STATUS.md](docs/STATUS.md) for their definitions.

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

Open items carried from verification (see [docs/STATUS.md](docs/STATUS.md)):

- Decide whether goals must reference a registered project (G3)
- Add a schema version to the state files and decide on file locking (the rest of G4)

## Phase 2 — Readiness and Execution Boundaries

Status: Implemented at the library level

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

"Implemented at the library level" is deliberate. The boundaries and the coordinator exist and are tested, but no CLI command invokes the coordinator (G6 in [docs/STATUS.md](docs/STATUS.md)). The manual lifecycle commands `aic task ready` and `aic task start` are gated by readiness; see Phase 2.5, Step 1.

## Phase 2.5 — Boundary Hardening

Status: In progress. Step 1 is implemented and Step 3 is partly implemented.

Purpose: make the boundaries built in Phase 2 actually bind every path, before any new capability depends on them.

### Step 1 — Gate manual lifecycle commands (closes G1)

Status: Implemented, using option 1.

Verified problem: a task in a failed goal can be moved `ready → running` from the CLI even though readiness reports it is not ready.

Options:

1. **Gate the CLI with the readiness boundary (recommended).** `aic task start` evaluates `TaskReadinessEvaluator` and refuses when the task is not ready. `aic task ready` refuses when the parent goal is missing, completed, or failed. No new CLI surface. Smallest change. Needs new tests for the CLI path.
2. **Route `aic task start` through `ExecutionStarter`.** This needs an execution target, so it means adding a `--target` argument or a default manual target. Larger and changes the CLI contract.
3. **Remove the manual `start`, `complete`, and `fail` commands** and allow those transitions only through the coordinator. This is the cleanest boundary, but removes the only way to exercise the lifecycle by hand until an execute command exists.
4. **Keep the behavior and document it** as a manual override. No code change, but it leaves INV-4 unenforced.

Option 1 is recommended because it closes the gap without changing what the commands are for.

### Step 2 — Decide and enforce project references (closes G3)

Either validate `--project` against the project registry at goal creation and in `aic validate`, or document free-text project names as intended.

### Step 3 — Crash-safe persistence (closes G4)

Status: Partly implemented. Atomic write-and-replace is done for all three JSON registries. An explicit schema version field and file locking are still open.

Scope: atomic write-and-replace for the JSON registries and an explicit schema version field, without changing the on-disk shape otherwise.

### Step 4 — Design the recovery path for `running` tasks (addresses G5)

Design before code: what marks a task as interrupted, and what transition is allowed out of `running` when no outcome was recorded.

### Step 5 — Execution records

A persisted record per execution attempt (request, admission result, outcome, timestamps). This is the minimum history needed for later recovery, evidence, and explainability.

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

Phase 3 depends on Phase 2.5 Steps 1 and 5.

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

## Phase 5 — Orchestration and Evidence

Status: Planned

- Task dependencies, moving from a flat list to a graph
- Event and workflow boundary
- Evidence attached to execution outcomes

## Phase 6 and beyond — Cognitive, Policy, and Agent Layers

Status: Research

These items come from exploratory design notes, not from a committed design. The ordering is provisional. Each item is described in [docs/DESIGN_DIRECTIONS.md](docs/DESIGN_DIRECTIONS.md).

- Deterministic cognitive foundation: nodes, relationships, provenance, populated by hand first
- Layered memory
- Policy and approval
- Tool registry
- Agent registry
- Local model interface
- Planner that proposes plans and does not execute them
- Real controlled execution by agents

These capabilities must not be introduced until the control boundaries beneath them bind every execution path.
