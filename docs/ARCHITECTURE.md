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
  execution/        contract, admission, start, outcome, records, registry, coordinator
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
| `running` | `completed`, `failed`, `ready` (only through `aic task requeue`) |
| `completed` | none |
| `failed` | none |

The transition table lives in the task model and is enforced by the task registry. Task lifecycle transitions are handled explicitly rather than being inferred from arbitrary execution behavior.

The `running` to `ready` transition exists for recovery, when the process running a task has died without recording an outcome. The table allows it, but the CLI reaches it only through `aic task requeue`, which requires a reason and refuses a task that is not `running` or whose parent goal is closed. `aic task ready` refuses a `running` task. See [RECOVERY_DESIGN.md](RECOVERY_DESIGN.md).

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

### Execution Records

An execution record describes one attempt to run a task. Records are stored in `executions.json`, next to the task file, through `ExecutionRecordRegistry` in `execution/records.py`. The registry takes its file path explicitly, and `ExecutionRecordRegistry.beside` places the file next to a task registry's file, which keeps tests that use temporary registries isolated from real user data.

A record has an `id`, a `task_id`, a `source` (`cli` or `coordinator`), an optional `target`, a `started_at`, an `ended_at`, an `ended_as` (`completed`, `failed`, `requeued` or `abandoned`) and a `reason`. An attempt is open until it ends. Ending a task that has no open record, which is the case for a task that was already running before records existed, writes a closed record with no start time.

Task status stays the authority, and the two files are written one after the other. Starting writes the open record first and then moves the task to `running`. Ending moves the task first and then closes the record. A crash between the two writes can therefore leave only one shape, an open record for a task that is not `running`, and never a `running` task whose record says it ended. When a task is next started, an open record left for it is closed as `abandoned`, in the same write that opens the new record.

The library (`ExecutionStarter` and `ExecutionOutcomeRecorder`) and the CLI (`aic task start`, `complete`, `fail` and `requeue`) both record, and parity tests require the records to have the same shape. A rejected request or a refused command writes nothing.

`aic validate` reports an open record whose task is not `running`, more than one open record for a task, a record whose task does not exist, and a repeated record ID. It accepts a `running` task with no record. `aic task history <task-id>` lists a task's attempts, oldest first. Both are read-only.

An attempt left open for a completed or failed task is never closed by the normal lifecycle (G11 in [STATUS.md](STATUS.md)). The design and its options are in [EXECUTION_RECORDS_DESIGN.md](EXECUTION_RECORDS_DESIGN.md).

## Execution Entry Points

A task can reach the `running` state through the execution boundary or through the CLI. Both paths enforce readiness.

| Path | What is enforced |
| --- | --- |
| `ExecutionCoordinator` / `ExecutionStarter` (library) | Readiness and admission; an attempt record is opened before the task moves to `running` |
| `aic task start` (CLI) | Readiness: the task must be `ready` and its parent goal must be open; an attempt record is opened before the task moves to `running` |
| `aic task ready` (CLI) | The parent goal must be open; a `running` task is refused |
| `aic task complete`, `aic task fail` (CLI) | The transition table: the task must be `running`; the attempt record is closed after the task moves |
| `aic task requeue` (CLI) | The task must be `running`, its parent goal must be open, and a reason is required; the attempt record is closed with the reason after the task moves |

The CLI commands use the same `TaskReadinessEvaluator` as the library path. `aic task start` evaluates full readiness. `aic task ready` can only check the parent goal, through `parent_goal_blocker`, because a task cannot be ready before that transition happens. Empty and unknown task IDs are left to the lifecycle transition, which reports them. `aic task requeue` is the only CLI path from `running` back to `ready`. It does not start the task: the task must still pass readiness through `aic task start`.

The CLI does not use `ExecutionStarter`, because that requires an execution target. A task started from the CLI is started by a person and is not handed to an adapter, so admission through a target applies to the library path only.

This closes G1 in [STATUS.md](STATUS.md). Before the fix, `aic task start` moved a task whose parent goal was failed to `running`, even though the readiness evaluator reported it as not ready.

## Persistence

State is stored as JSON files in a local data directory.

| File | Content |
| --- | --- |
| `projects.json` | Registered projects |
| `goals.json` | Goals |
| `tasks.json` | Tasks |
| `executions.json` | Execution attempt records, created when the first attempt is recorded |

The data directory is resolved in this order:

1. The `AIC_DATA_DIR` environment variable, if set.
2. On Windows, `%LOCALAPPDATA%\AI-Control-Centre`, falling back to `~\AppData\Local\AI-Control-Centre`.
3. Otherwise `~/.local/share/ai-control-centre`.

Identifiers are UUID4 strings. Timestamps are UTC ISO-8601 strings. Each registry accepts an explicit file path, which the tests use to stay isolated from real user data.

Each file is a JSON object with a `schema_version` number and a list of items under the name of its collection: `projects`, `goals`, `tasks`, or `executions`. For example, `goals.json` holds `{"schema_version": 1, "goals": [...]}`.

Files written before versioning are a bare JSON list. They are read as schema version 1 and are rewritten in the versioned shape the next time they are saved. Reading never modifies a file. A file whose `schema_version` is higher than this version of the tool supports is refused and left untouched, and so is a file that is not valid JSON or does not have the expected shape. The CLI reports these errors as `Error: ...` and exits with status 1. When the shape of a state file changes, `SCHEMA_VERSION` in `storage.py` is raised and a migration from the previous version is added.

Writes are atomic. Each registry writes through `write_text_atomic` in `storage.py`: the text goes to a temporary file in the same directory, is flushed to disk, and then replaces the state file with `os.replace`. A crash or error during a write leaves the previous file intact, and the temporary file is removed.

Current limitations of persistence:

- There is no file locking, so concurrent processes can still overwrite each other's changes.
- A hard kill during a write can leave a stale temporary file named `.<file>.<id>.tmp`. The registries ignore it.
- Tasks store only `created_at` and `updated_at`. Execution attempts are recorded in `executions.json`, but there is no history of other status changes.

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

Concrete system-level execution adapters, execution permissions, execution limits, timeouts, post-execution validation, diagnostics, automatic recovery of interrupted runs, and stronger isolation remain future work. A person can already recover a stuck `running` task with `aic task requeue`.

The execution adapter interface therefore represents a controlled architectural extension point rather than an unrestricted command or automation interface.

Future execution capabilities must preserve the existing lifecycle, readiness, admission, and outcome boundaries. The CLI lifecycle commands already follow this rule; see "Execution Entry Points".
