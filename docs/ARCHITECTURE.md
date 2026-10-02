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

Goals currently refer to a project by free-text name. The name is not checked against the project registry (see G3 in [STATUS.md](STATUS.md)).

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

The validator checks for duplicate goal and task IDs, unknown goal and task statuses, tasks that reference a missing goal, and goals whose persisted status differs from the status derived from their tasks.

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

The goal checks run before the task status check. A `pending` task in a failed goal therefore reports "parent goal is failed", not "task status is pending".

Readiness does not itself mutate lifecycle state.

A task must satisfy the readiness contract before execution-specific starting is allowed. See "Execution Entry Points" below for where this is and is not enforced today.

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

There are two ways a task reaches the `running` state today, and they do not enforce the same rules.

| Path | Readiness and admission enforced |
| --- | --- |
| `ExecutionCoordinator` / `ExecutionStarter` (library) | Yes |
| `aic task start` (CLI) | **No** |

The CLI lifecycle commands `aic task ready`, `start`, `complete`, and `fail` call the task registry directly. They enforce the transition table but not readiness. As a result, a task whose parent goal is failed can still be moved to `running` from the CLI, even though the readiness evaluator reports it as not ready. This was reproduced and is tracked as G1 in [STATUS.md](STATUS.md), with proposed resolutions in [ROADMAP.md](../ROADMAP.md).

Until that gap is closed, the readiness and admission boundaries bind the library execution path but not every path.

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

Current limitations of persistence:

- Writes are direct file writes, not atomic replacements.
- There is no file locking.
- Files carry no schema version.
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

Future execution capabilities must preserve the existing lifecycle, readiness, admission, and outcome boundaries. That requirement currently has one open exception: the CLI lifecycle commands (see "Execution Entry Points").
