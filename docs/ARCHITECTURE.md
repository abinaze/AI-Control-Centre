# Architecture

## Overview

AI Control Centre is a local-first control platform built around deterministic state transitions and explicit control boundaries.

The architecture is intentionally incremental. Each major capability is introduced through a defined contract, an implementation boundary, and tests that verify its observable behavior.

This document describes what exists in the code. Where it mentions something that does not exist yet, it says so. For the verified state, known gaps, and invariants, see [STATUS.md](STATUS.md). For exploratory future directions, see [DESIGN_DIRECTIONS.md](DESIGN_DIRECTIONS.md).

The current architecture is centered on the following progression:

```text
Project
  ↓
Goal
  ↓
Task
  ↓
Lifecycle
  ↓
Validation
  ↓
Readiness
  ↓
Execution Admission
  ↓
Execution Start
  ↓
Execution Coordination
  ↓
Execution Adapter
  ↓
Execution Outcome
```

This progression separates state management and control decisions from the eventual execution mechanism.

## Module Map

```text
src/aic_control_centre/
  cli.py            argparse entry point (the `aic` command)
  config.py         data directory and state file locations
  doctor.py         environment checks (Python version, git on PATH)
  storage.py        atomic writes and versioned reads of state files
  projects/         project registry and commands
  goals/            goal model, registry, and commands
  tasks/            task model (lifecycle table), registry, and commands
  orchestration/    goal status derivation and reconciliation
  validation/       goal/task validation and the task-creation rule
  readiness/        task readiness evaluator
  execution/        contract, admission, start, outcome, registry, coordinator
```

## Core Lifecycle Model

The core domain is organized around projects, goals, and tasks.

### Project

A project is the top-level persisted unit of work. It is a registered local directory; its name is the directory name.

Project state is stored locally and managed through deterministic commands.

A goal refers to a project by name. `aic goal create` refuses a project that is not registered, and `aic validate` reports goals whose project is not registered. Names are matched exactly.

### Goal

A goal represents a desired outcome within a project.

Goals have an explicit lifecycle: `pending`, `in_progress`, `completed`, `failed`.

A goal's status is derived from its tasks:

| Tasks | Derived goal status |
| --- | --- |
| None | `pending` |
| Any task `failed` | `failed` |
| All tasks `completed` | `completed` |
| Otherwise | `in_progress` |

Reconciliation persists the derived status into the goal. A goal that is `completed` or `failed` does not accept new tasks.

### Task

A task represents an actionable unit of work associated with a goal.

Tasks have an explicit lifecycle. Transitions are allowed only as follows:

| From | To |
| --- | --- |
| `pending` | `ready` |
| `ready` | `running` |
| `running` | `completed`, `failed` |
| `completed` | none |
| `failed` | none |

The transition table lives in the task model and is enforced by the task registry. Task lifecycle transitions are handled explicitly rather than being inferred from arbitrary execution behavior.

## Validation Boundary

Validation provides a deterministic boundary for checking persisted project state.

The validator checks for duplicate goal and task IDs, unknown goal and task statuses, tasks that reference a missing goal, goals whose project is not registered, and goals whose persisted status differs from the status derived from their tasks. The project check runs only when the validator is given a project registry; `aic validate` always gives it one.

Validation reports state inconsistencies and invalid conditions without modifying persisted state. It is a read-only operation.

## Readiness Boundary

Readiness determines whether a task is allowed to cross into execution.

The readiness evaluator produces an explicit result and reason. It checks, in order:

1. The task exists.
2. The parent goal exists.
3. The parent goal has a known status.
4. The parent goal is not `completed`.
5. The parent goal is not `failed`.
6. The task status is `ready`.

The goal checks run before the task status check. A `pending` task in a failed goal therefore reports "parent goal is failed", not "task status is pending". Checks 2 to 5 are also available on their own as `parent_goal_blocker`.

Readiness does not itself mutate lifecycle state.

A task must satisfy the readiness contract before it can start, whether it starts through the execution boundary or through the CLI. See "Execution Entry Points" below.

## Execution Architecture

Execution is separated into explicit boundaries so that execution control is not coupled directly to a concrete execution mechanism.

### Execution Request

An execution request identifies the task and the requested execution target.

The request contract validates that both values are non-empty.

### Execution Admission

Execution admission evaluates whether the requested task satisfies the readiness boundary.

Admission produces an explicit accepted or rejected result and does not itself mutate task state.

### Execution Start

The execution start boundary performs admission and, when admission succeeds, transitions the task from ready to running.

Starting execution is therefore distinct from executing the task.

### Execution Target

An execution target identifies which registered execution adapter should handle a request.

The adapter registry provides explicit target registration and resolution.

Unknown targets are rejected before the task is started so that target resolution cannot leave a task in a running state without a valid execution adapter.

### Execution Adapter

An execution adapter receives an execution request and returns an execution outcome.

The current architecture defines this as a protocol boundary. No concrete adapter exists yet; the tests use test doubles.

Adapter failures are handled by the coordinator and converted into a failed execution outcome.

### Execution Outcome

An execution outcome identifies the task and declares a completed or failed result.

Outcome recording is responsible for persisting the resulting task state and reconciling the associated goal.

The outcome recorder only accepts execution outcomes for tasks that are currently running.

### Execution Coordination

The execution coordinator connects the execution boundaries in a deterministic sequence:

1. Resolve the requested execution target.
2. Admit the task through the readiness boundary.
3. Start the task and transition it to running.
4. Invoke the resolved execution adapter.
5. Validate the adapter result.
6. Record the resulting execution outcome.
7. Return a structured coordination result.

The coordination result has a status of `rejected`, `completed`, or `failed`. A `rejected` result carries no outcome and means the task was never started, or the outcome could not be recorded.

Adapter exceptions, invalid adapter results, and task identity mismatches are converted into controlled failure outcomes rather than being allowed to bypass outcome recording.

The coordinator is a library component. No CLI command invokes it today.

## Execution Entry Points

A task can reach the `running` state through the execution boundary or through the CLI. Both paths enforce readiness.

| Path | What is enforced |
| --- | --- |
| `ExecutionCoordinator` / `ExecutionStarter` (library) | Readiness and admission |
| `aic task start` (CLI) | Readiness: the task must be `ready` and its parent goal must be open |
| `aic task ready` (CLI) | The parent goal must be open |
| `aic task complete`, `aic task fail` (CLI) | The transition table: the task must be `running` |

The CLI commands use the same `TaskReadinessEvaluator` as the library path. `aic task start` evaluates full readiness. `aic task ready` can only check the parent goal, through `parent_goal_blocker`, because a task cannot be ready before that transition happens. Empty and unknown task IDs are left to the lifecycle transition, which reports them.

The CLI does not use `ExecutionStarter`, because that requires an execution target. A task started from the CLI is started by a person and is not handed to an adapter, so admission through a target applies to the library path only.

This closes G1 in [STATUS.md](STATUS.md). Before the fix, `aic task start` moved a task whose parent goal was failed to `running`, even though the readiness evaluator reported it as not ready.

## Persistence

State is stored as JSON files in a local data directory.

| File | Content |
| --- | --- |
| `projects.json` | Registered projects |
| `goals.json` | Goals |
| `tasks.json` | Tasks |

The data directory is resolved in this order:

1. The `AIC_DATA_DIR` environment variable, if set.
2. On Windows, `%LOCALAPPDATA%\AI-Control-Centre`, falling back to `~\AppData\Local\AI-Control-Centre`.
3. Otherwise `~/.local/share/ai-control-centre`.

Identifiers are UUID4 strings. Timestamps are UTC ISO-8601 strings. Each registry accepts an explicit file path, which the tests use to stay isolated from real user data.

Each file is a JSON object with a `schema_version` number and a list of items under the name of its collection: `projects`, `goals`, or `tasks`. For example, `goals.json` holds `{"schema_version": 1, "goals": [...]}`.

Files written before versioning are a bare JSON list. They are read as schema version 1 and are rewritten in the versioned shape the next time they are saved. Reading never modifies a file. A file whose `schema_version` is higher than this version of the tool supports is refused and left untouched, and so is a file that is not valid JSON or does not have the expected shape. The CLI reports these errors as `Error: ...` and exits with status 1. When the shape of a state file changes, `SCHEMA_VERSION` in `storage.py` is raised and a migration from the previous version is added.

Writes are atomic. Each registry writes through `write_text_atomic` in `storage.py`: the text goes to a temporary file in the same directory, is flushed to disk, and then replaces the state file with `os.replace`. A crash or error during a write leaves the previous file intact, and the temporary file is removed.

Current limitations of persistence:

- There is no file locking, so concurrent processes can still overwrite each other's changes.
- A hard kill during a write can leave a stale temporary file named `.<file>.<id>.tmp`. The registries ignore it.
- Only `created_at` and `updated_at` are stored. There is no transition or execution history.

See G4 in [STATUS.md](STATUS.md).

## Design Principles

### Explicit Boundaries

Major state transitions and execution decisions are represented by explicit boundaries rather than implicit side effects.

### Deterministic Behavior

The same persisted state and request should produce predictable control decisions.

### Separation of Concerns

Lifecycle management, validation, readiness, execution control, adapter resolution, and outcome recording remain separate responsibilities.

### Validation Does Not Repair

Validation is read-only. It reports that persisted state is inconsistent and does not change it.

Reconciliation is a separate, explicit operation that does write. It runs when a goal's status is viewed with `aic goal status`, when a task is created, when a task's status changes through the CLI, and when an execution outcome is recorded. Reconciliation only recomputes a goal's status from its tasks. It does not change task state, and it does not repair other kinds of inconsistency.

This means a read-looking command, `aic goal status`, can write to `goals.json`. That behavior is intentional and covered by tests. It does mean that a mismatch reported by `aic validate` can disappear after `aic goal status` is run.

### Controlled Failure

Execution failures are converted into explicit outcomes so that failure handling remains inside the execution boundary.

## Design Direction

The project is expected to grow a second, separate pillar: a cognitive layer that holds knowledge, relationships, memory, and context. The governing rule is that the cognitive layer may propose, relate, and remember, while the deterministic control layer alone decides what is permitted to happen, and control state remains authoritative.

None of this exists in code. It is recorded as research in [DESIGN_DIRECTIONS.md](DESIGN_DIRECTIONS.md).

## Current Limitations

The current architecture does not yet provide unrestricted execution capabilities.

Concrete system-level execution adapters, execution permissions, execution limits, timeouts, post-execution validation, diagnostics, recovery, and stronger isolation remain future work.

The execution adapter interface therefore represents a controlled architectural extension point rather than an unrestricted command or automation interface.

Future execution capabilities must preserve the existing lifecycle, readiness, admission, and outcome boundaries. The CLI lifecycle commands already follow this rule; see "Execution Entry Points".
