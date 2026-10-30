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
  storage.py        atomic writes and versioned reads of state files, and the reader for a file that may be absent
  locking.py        the exclusive state lock held for one CLI command
  timestamps.py     reading the times that the registries write
  projects/         project registry, commands and the directory check
  goals/            goal model, registry, and commands
  tasks/            task model (lifecycle table), registry, commands, and the running task report
  orchestration/    goal status derivation and reconciliation
  validation/       goal/task validation and the task-creation rule
  readiness/        task readiness evaluator
  permissions/      grant model, registry and commands
  execution/        contract, admission, start, outcome, records, registry, coordinator, adapters, process, grants, projects, snapshot, readonly, inspect_project
```

## Core Lifecycle Model

The core domain is organized around projects, goals, and tasks.

### Project

A project is the top-level persisted unit of work. It is a registered local directory; its name is the directory name.

Project state is stored locally and managed through deterministic commands.

A goal refers to a project by name. `aic goal create` refuses a project that is not registered, and `aic validate` reports goals whose project is not registered. Names are matched exactly.

A project name belongs to one directory, because a goal or a grant that names a project does not say which directory it means. `aic project add` refuses a second directory with a name that is already registered and says which path holds it, and registering the same directory again returns the project that exists. `aic validate` reports a name that more than one directory has. `aic project remove` removes an entry that nothing still names (see Removing a project below). `aic validate` also reports a registered directory that does not exist or is not a directory. `aic project list` only lists, and does not look at the directories.

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

The validator checks for duplicate goal and task IDs, unknown goal and task statuses, tasks that reference a missing goal, goals whose project is not registered, project names that more than one directory has, registered project directories that do not exist or are not directories, and goals whose persisted status differs from the status derived from their tasks. The project checks run only when the validator is given a project registry; `aic validate` always gives it one. It also reports a `created_at`, `updated_at`, `started_at`, `ended_at`, `granted_at` or `revoked_at` that cannot be read as ISO 8601 text with an offset. Goals and tasks are always checked, and execution records and grants are checked when their registries are given. A time that the model allows to be empty is not an error when it is empty. `read_time` in `timestamps.py` is the one reader, and `aic task running` uses it too. A bad time is reported and never refused when the state is loaded, so the commands that recover from it still run.

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

The current architecture defines this as a protocol boundary. There are two concrete adapters, both in `execution/adapters.py`: `noop`, which completes a task without doing any work, and `inspect`, which reports what is in a project directory. `build_adapter_registry` registers adapters in code; nothing is loaded by name from configuration. The tests use test doubles for everything else.

Adapter failures are handled by the coordinator and converted into a failed execution outcome.

The coordinator can be given a state guard: a function that returns a context manager holding the state lock. It enters the guard around the start and around each outcome recording, and never while an adapter runs, so a person can still run `aic task requeue` during a long run. A coordinator without a guard takes no lock, so a caller of the library that runs more than one process must pass one.

### Process adapters

An adapter that runs inside the CLI process cannot be stopped if it hangs. `ProcessAdapter`, in `execution/process.py`, is an ordinary adapter that runs a fixed command in a child process instead, so the coordinator needs no change. The command is a list written in code. Nothing from a task is placed in it or in the child's environment. The request goes to the child as one JSON object on standard input, which holds the task ID and the target and, for an adapter that needs a project, the registered path of the project directory, and the child answers with one JSON object on standard output and exit status 0.

AIC stops the child, and the processes it started, when the run takes longer than its timeout, when standard output or standard error passes its cap, or when the command is interrupted. A timeout or too much output is a failed outcome with a reason, recorded like any other outcome. A non-zero exit, output that is not that object, and an unknown outcome are failed outcomes too. The child inherits only a short list of environment variables and runs in a new empty temporary directory that is removed afterwards.

On Linux the child starts in its own session, and its whole group is stopped. On Windows the tree is stopped with `taskkill /F /T` while the child is alive. If AIC itself is killed, the child keeps running, and the task is left `running` with its attempt open. CPU and memory limits are not enforced. These limits are listed as G13 in [STATUS.md](STATUS.md). `inspect` is registered as a process adapter.

### Grants

A target that does real work must not run for a project until a person has allowed it. `ExecutionRequest` has a `requires_grant` field that defaults to true, and an adapter can declare `requires_grant`. An adapter that says nothing is treated as needing a grant, and `noop`, which does nothing, declares that it needs none. The coordinator marks the request that it gives to the starter from the adapter, never from the caller.

Admission, which runs inside the start and so inside one entry of the state guard, asks a grant source whether the project of the task may use the target. `NoGrants`, the default source, allows nothing. A request that is not covered is refused with `target X is not granted for project Y`, and nothing is written. `PermissionRegistry`, in `permissions/registry.py`, is a grant source that keeps grants in `permissions.json` next to the task file, and `aic task run` gives it to admission. A grant records a project, a target, a reason and when it was made, and it is active until it is revoked. A revoked grant stays in the file as history. The registry reads the file on every question, and a file that cannot be read is an error, never an empty answer. `aic validate` reports a repeated grant ID, an active grant that repeats another, and an active grant for a project or a target that does not exist. `aic permission grant` makes a grant for a registered project and a registered target and needs a reason, `aic permission revoke` ends it even if the project or the target has since been removed, and `aic permission list` shows the active grants, or all of them with `--all`. `grant` and `revoke` take the state lock, and `list` does not. `aic task targets` says which targets need a grant. No command asks for confirmation, because the CLI cannot tell a person from a program. The design, including what grants cannot protect against, is in [PERMISSIONS_DESIGN.md](PERMISSIONS_DESIGN.md).

### Project directories

A target that acts on the files of a project needs to know where the project is. `ExecutionRequest` has a `requires_project` field that defaults to false, and an adapter can declare `requires_project`. An adapter that says nothing needs no project, and `noop` is one. The coordinator marks the request that it gives to the starter from the adapter, never from the caller.

Admission, inside the same entry of the state guard as the grant check, asks a project source for the project of the task. `NoProjects`, the default source, finds nothing, and `ProjectRegistry` is a source that `aic task run` gives to admission. After readiness and before the grant check, a request is refused when the project is not registered, when its directory does not exist, when its path is not a directory, and when the directory cannot be looked at. The reason names the project, and nothing is written. The directory is looked at once with `os.stat`, in `projects/directory.py`, which tells a directory that is not there from a path that is not a directory and from one that cannot be read, and gives the reason that the system gave. `Path.exists()` and `Path.is_dir()` are not used, for the same reason as above (G17 in [STATUS.md](STATUS.md)). The accepted result and the start result carry the registered path, and the coordinator gives the adapter its request with that path. A path that a caller put in the request is dropped. The directory is checked once, at admission, so it can still vanish before the adapter works, and an adapter has to treat that as a failed outcome. A `ProcessAdapter` created with `requires_project=True` sends the path as `project_path` in the JSON on the child's standard input and nowhere else, and it fails without starting the child when it has no path. The design is in [FIRST_ADAPTER_DESIGN.md](FIRST_ADAPTER_DESIGN.md). `inspect` needs one.

### Read-only runs

An adapter that is meant to only read a project is wrapped in `ReadOnlyAdapter`. The wrapper takes a snapshot of the project before the run and another after it, with `take_snapshot` in `execution/snapshot.py`, and a run that left the project different is a failed outcome. A snapshot lists every file with its size, its modification time in nanoseconds and the SHA-256 of its content, every directory, and every link. A link is recorded with its target and is never followed. A Windows junction is recognised by its reparse tag, because its mode looks like a directory. A file that is not a regular file is listed and never opened. Anything that cannot be read is recorded as unreadable, and is the same in both snapshots unless it changes. The content hash is compared as well as the size and the time, because a modification time can advance in coarse steps.

The wrapper always needs a project, so admission checks the directory first, and it takes the grant rule and the description of the adapter it wraps. If the project cannot be read before the run, the adapter does not run. If it cannot be read after the run, the run fails. A change is reported even when the adapter said it succeeded or raised an error, with the counts and at most three escaped names in a reason that starts `the project changed during a read-only run`. This detects a change and does not prevent one. It sees only the project, it cannot tell who made a change, it is not a sandbox, and the snapshots are not limited in time or in the number of files (G16 in [STATUS.md](STATUS.md)). `inspect` is wrapped in it.

### Removing a project

`aic project remove <name> [--path <directory>]` removes one entry from `projects.json` and never touches the directory. Goals and grants identify a project by its name, so a removal that left one of them pointing at a name that is no longer registered would bring back the problem that unique names closed: the name could be registered again for another directory, and the old goals would attach to it. The command therefore refuses, writes nothing, and lists what still uses the project: the goals that name it, with their ids and statuses and at most five shown, and the active grants, with their targets. A revoked grant is history and does not block. Goals cannot be removed (G20 in [STATUS.md](STATUS.md)), so a project that has ever had a goal stays registered.

A name that more than one directory has does not say which entry is meant. The command refuses it and shows the directories, and `--path` picks one. The directory is compared as a resolved path and may be one that no longer exists. Another entry keeps the name in that case, so goals and grants do not block the removal. This is the repair for the state that `aic validate` reports as one name held by two directories. The command holds the state lock for the whole command, as every command that writes does. The rules are in `removal_blockers` in `projects/removal.py` and in `find_project` and `remove_project` in `projects/registry.py`.

Two options were rejected: removing the entry and leaving the goals and grants pointing at a name that is not registered, which `aic validate` would then report, and removing the goals, tasks and records together with the project, which destroys the audit trail.

### The inspect adapter

`inspect` is the first adapter that does real work, and it only reads. It is registered in `execution/adapters.py` by `build_inspect_adapter` as a `ReadOnlyAdapter` around a `ProcessAdapter` that runs `sys.executable -m aic_control_centre.execution.inspect_project`, so it needs a grant and a project, and a run is refused before anything starts when either is missing. The request reaches the child as JSON on standard input with the `project_path` that admission returned. The child starts in an empty temporary directory with a short environment and no `PYTHONPATH`, so it works only on the path that it is given, and AIC has to be installed for it to start (G19 in [STATUS.md](STATUS.md)).

The module `execution/inspect_project.py` is both the library and the child. `inspect_directory` walks the project with directory listings and file status only. It never opens a file and never follows a link, counts files, directories, links, other entries and entries that it could not read, adds up the size of the files, keeps the three largest, and notes a README and a `.git` at the top level. `describe` writes the result as one line, with names that are escaped and cut, so the reason is short whatever the project holds. The child answers every request with one JSON line and exit status 0, and a request that cannot be done is a failed outcome with a reason. The snapshots of the wrapper do read every file to hash it, so a run reads the content of the project twice although `inspect` itself does not. The design is in [FIRST_ADAPTER_DESIGN.md](FIRST_ADAPTER_DESIGN.md).

### Execution Outcome

An execution outcome identifies the task and declares a completed or failed result.

Outcome recording is responsible for persisting the resulting task state and reconciling the associated goal.

The outcome recorder only accepts execution outcomes for tasks that are currently running.

An outcome can also name the attempt it belongs to. The coordinator does, using the attempt ID that the start result returns. The recorder then refuses the outcome, and changes nothing, unless that attempt is still the task's open attempt. This stops a run that was superseded while its adapter ran, for example by `aic task requeue` and a restart, from closing the newer attempt. Outcomes that name no attempt, such as those recorded by the CLI, are accepted as before.

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

`aic task run <task-id> --target <name>` runs a ready task through the coordinator. It prints the task, the target, a result (`completed`, `failed` or `rejected`) and a reason, and it exits 0 only for `completed`. `aic task targets` lists the registered targets and says whether each needs a grant. The command passes a state guard, described under State locking, so the lock is held only while state is read or written.

### Execution Records

An execution record describes one attempt to run a task. Records are stored in `executions.json`, next to the task file, through `ExecutionRecordRegistry` in `execution/records.py`. The registry takes its file path explicitly, and `ExecutionRecordRegistry.beside` places the file next to a task registry's file, which keeps tests that use temporary registries isolated from real user data.

A record has an `id`, a `task_id`, a `source` (`cli` or `coordinator`), an optional `target`, a `started_at`, an `ended_at`, an `ended_as` (`completed`, `failed`, `requeued` or `abandoned`) and a `reason`. An attempt is open until it ends. Ending a task that has no open record, which is the case for a task that was already running before records existed, writes a closed record with no start time. The reason comes from `aic task requeue`, from `--reason` on `aic task complete` or `aic task fail`, or from the outcome that the coordinator records. It is empty when none was given.

Task status stays the authority, and the two files are written one after the other. Starting writes the open record first and then moves the task to `running`. Ending moves the task first and then closes the record. A crash between the two writes can therefore leave only one shape, an open record for a task that is not `running`, and never a `running` task whose record says it ended. When a task is next started, an open record left for it is closed as `abandoned`, in the same write that opens the new record.

The library (`ExecutionStarter` and `ExecutionOutcomeRecorder`) and the CLI (`aic task start`, `complete`, `fail` and `requeue`) both record, and parity tests require the records to have the same shape. A rejected request or a refused command writes nothing.

`aic validate` reports an open record whose task is not `running`, more than one open record for a task, a record whose task does not exist, and a repeated record ID. It accepts a `running` task with no record. `aic task history <task-id>` lists a task's attempts, oldest first. Both are read-only.

`aic task running` lists the `running` tasks and how long each has been running, longest first. A task is timed from the start of its latest open attempt. A running task with no open attempt began before records existed, so it is timed from its last update and marked as an estimate. A start time that cannot be read, because it is not a time or has no offset, is listed as unknown and is kept by the `--older-than` filter. A start time in the future is listed and counts as zero. The command is advisory: a live run and a killed run leave the same record, so it says how long and never whether anything is still running the task. It writes nothing and takes no lock. The design is in [STALE_TASKS_DESIGN.md](STALE_TASKS_DESIGN.md).

An attempt left open for a completed or failed task is never closed by the normal lifecycle (G11 in [STATUS.md](STATUS.md)). The design and its options are in [EXECUTION_RECORDS_DESIGN.md](EXECUTION_RECORDS_DESIGN.md).

## Execution Entry Points

A task can reach the `running` state through the execution boundary or through the CLI. Both paths enforce readiness.

| Path | What is enforced |
| --- | --- |
| `ExecutionCoordinator` / `ExecutionStarter` (library) | Readiness and admission; an attempt record is opened before the task moves to `running` |
| `aic task start` (CLI) | Readiness: the task must be `ready` and its parent goal must be open; an attempt record is opened before the task moves to `running` |
| `aic task ready` (CLI) | The parent goal must be open; a `running` task is refused |
| `aic task complete`, `aic task fail` (CLI) | The transition table: the task must be `running`; the attempt record is closed after the task moves, and an optional `--reason` is stored in it |
| `aic task requeue` (CLI) | The task must be `running`, its parent goal must be open, and a reason is required; the attempt record is closed with the reason after the task moves |
| `aic task run` (CLI) | The same admission as the library path: the task must be `ready` and its parent goal open, and the target must be registered. The task moves to `running`, the adapter runs, and the outcome is recorded against the attempt that was started |

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
| `permissions.json` | Grants, created when the first grant is made |
| `.aic.lock` | The state lock, created by the first command that locks. It is never deleted and holds no data |

The data directory is resolved in this order:

1. The `AIC_DATA_DIR` environment variable, if set.
2. On Windows, `%LOCALAPPDATA%\AI-Control-Centre`, falling back to `~\AppData\Local\AI-Control-Centre`.
3. Otherwise `~/.local/share/ai-control-centre`.

Identifiers are UUID4 strings. Timestamps are UTC ISO-8601 strings. Each registry accepts an explicit file path, which the tests use to stay isolated from real user data.

Each file is a JSON object with a `schema_version` number and a list of items under the name of its collection: `projects`, `goals`, `tasks`, or `executions`. For example, `goals.json` holds `{"schema_version": 1, "goals": [...]}`.

Files written before versioning are a bare JSON list. They are read as schema version 1 and are rewritten in the versioned shape the next time they are saved. Reading never modifies a file. A file whose `schema_version` is higher than this version of the tool supports is refused and left untouched, and so is a file that is not valid JSON or does not have the expected shape. The CLI reports these errors as `Error: ...` and exits with status 1. A file that cannot be read for any other reason is the same kind of error, and it names the file and the reason that the system gave. Only a file that is not there is an empty registry, through `read_state_items_or_empty`, which every registry uses. `Path.exists()` is not used for this, because on some Python versions, including 3.14 on Windows, it answers no for any error, and an empty registry would let the next save overwrite what was saved (G18 in [STATUS.md](STATUS.md)). When the shape of a state file changes, `SCHEMA_VERSION` in `storage.py` is raised and a migration from the previous version is added.

Writes are atomic. Each registry writes through `write_text_atomic` in `storage.py`: the text goes to a temporary file in the same directory, is flushed to disk, and then replaces the state file with `os.replace`. A crash or error during a write leaves the previous file intact, and the temporary file is removed.

### State locking

Atomic writes protect against a crash. They do nothing for two processes that overlap, because each registry reads a whole file, changes it in memory and writes it back, so the later write wipes out the earlier one. The CLI therefore holds one exclusive lock for the whole of a command.

`state_lock(data_dir)` in `locking.py` locks one byte of `.aic.lock` in the data directory with the operating system: `fcntl.flock` on Unix-like systems and `msvcrt.locking` on Windows. Other processes retry every 20 ms for 10 seconds and then fail with `StateLockError`, which `main` reports as `Error: another aic process is using the state files (waited 10s).` and exit status 1, having changed nothing. The operating system releases the lock when its holder ends, even if it was killed. A second acquisition in the same process raises `StateLockError`, because it would otherwise wait for itself.

`main` takes the lock around `_run`, once per process. Library code does not lock. Every command locks for its whole run except those listed in `READ_ONLY_COMMANDS`: `doctor`, `project list`, `goal list`, `permission list`, and `task list`, `status`, `readiness`, `history`, `targets` and `running`; and those in `SELF_LOCKING_COMMANDS`: `task run`. A self-locking command takes the lock itself, around each state operation, because it runs something slow in between. `aic validate` locks, because it reads four files and should see them agree. A command that only prints help takes no lock. The default is to lock, so a new command is protected until someone decides that it only reads. A test lists every command the parser knows and fails if one is not classified.

A read-only command sees one file at a time and each file is always complete, so it never reads a half-written file. On Windows such a reader can hold a state file open at the moment a writer replaces it, so `write_text_atomic` retries `os.replace` up to five times, 50 ms apart, after a `PermissionError`. Other errors are not retried.

The lock is never held while an adapter runs. `aic task run` takes it for the start and again for recording the outcome. If the lock cannot be taken to record the outcome, the adapter has already run. The command says so, and the task is left `running` with its attempt open, the same shape a crash leaves, which `aic task requeue`, `complete` or `fail` recovers.

Current limitations of persistence:

- The state lock is advisory. It keeps `aic` processes apart; it does not stop a person editing a state file by hand or a sync tool copying it, and it is not reliable on network file systems.
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

Concrete system-level execution adapters beyond `inspect`, limits on what an adapter may touch, execution limits, timeouts, post-execution validation, diagnostics, automatic recovery of interrupted runs, and stronger isolation remain future work. A person can already recover a stuck `running` task with `aic task requeue`.

The execution adapter interface therefore represents a controlled architectural extension point rather than an unrestricted command or automation interface.

Future execution capabilities must preserve the existing lifecycle, readiness, admission, and outcome boundaries. The CLI lifecycle commands already follow this rule; see "Execution Entry Points".
