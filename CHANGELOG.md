# Changelog

All notable changes to AI Control Centre are documented here.

## Unreleased

### Changed

- `aic task start` now evaluates task readiness and refuses to start a task that is not ready, for example when its parent goal is failed or completed. It reports the readiness reason instead of the generic invalid-transition error.
- `aic task ready` now refuses when the parent goal is missing, completed, failed, or has an invalid status.
- `TaskReadinessEvaluator.parent_goal_blocker` exposes the parent goal check, and `evaluate` now uses it.
- The project, goal, and task registries now write their JSON files atomically: a temporary file, a flush to disk, then a replace. A crash or error during a write no longer risks leaving a truncated state file.
- Added `aic_control_centre.storage.write_text_atomic`, the helper the registries use.
- State files now record a schema version. Each file is a JSON object with a `schema_version` number and its items under `projects`, `goals`, or `tasks`. Files that are a bare list, as written by earlier versions, are read as version 1 and are rewritten in the new shape the next time they are saved.
- Upgrade note: once a state file has been saved in the new shape, versions of the tool from before this change cannot read it. Back up the data directory before upgrading if you may need to go back.
- A state file that is not valid JSON, has an unusable `schema_version`, or was written by a newer schema version is now reported as `Error: ...` with exit status 1 instead of a traceback, and is not modified.
- Added `read_state_items`, `serialize_state_items`, `StateFileError`, and `UnsupportedSchemaVersionError` to `aic_control_centre.storage`.
- `aic goal create` now refuses a project that is not registered and points to `aic project add <path>`. Project names are matched exactly.
- `aic validate` now reports goals whose project is not registered. Upgrade note: goals created earlier for an unregistered project are not modified, but `aic validate` fails until that project is registered with `aic project add <path>`.
- Added `ProjectRegistry.get_project` and an optional `project_registry` argument to `GoalTaskValidator`. The project check runs only when that argument is given.
- Added `aic task requeue <task-id> --reason "<text>"`. It returns a `running` task to `ready`, so a task whose process died can be retried through readiness without failing its goal. A reason is required. The command refuses a task that is not `running` and a task whose parent goal is missing, completed, failed, or has an invalid status. It does not start the task and never changes a goal to a closed status. The reason is printed and stored in the attempt record.
- The task transition table now allows `running → ready`. `aic task ready` refuses a `running` task and points to `aic task requeue`, so the new edge is reached only through requeue.
- Added execution attempt records in `executions.json`, next to the task file, with the registry in `execution/records.py`. `ExecutionStarter` opens a record when it starts a task, and `ExecutionOutcomeRecorder` closes it with the outcome and its reason, so outcome reasons and adapter failure reasons are no longer dropped. A task that was already running before records existed gets a closed record with no start time.
- `aic task start` opens an attempt record before the task moves to `running`, and `aic task complete`, `fail` and `requeue` close it after the task moves. A requeue stores its reason in the record. A corrupt or newer-version `executions.json` stops `aic task start` before the task changes. The other three report it as an error after the task has already moved.
- `aic validate` now checks the execution records. It reports an open record whose task is not `running`, more than one open record for a task, a record whose task does not exist, and a repeated record ID. A `running` task with no record is accepted, because tasks started before records existed have none. Checking is read-only.
- Added `aic task history <task-id>`: the attempts for a task, oldest first, with route, start, end, outcome and reason. An open attempt for a task that is not running is flagged. The command is read-only.
- `KNOWN_GOAL_STATUSES` is now defined once, in `goals/model.py`, and readiness and validation import it (G10).
- `aic --version` reads the package version instead of repeating the string, and a test requires `pyproject.toml` and the package to agree (G7).
- Removed the unused `AppConfig.state_dir`. `AppConfig.default_model_provider` is kept, because it is a documented reserved setting (G7).
- Added `aic_control_centre.locking.state_lock`, an exclusive operating system lock on `.aic.lock` in the data directory. `main` holds it for the whole of every command except `doctor`, the `list`, `status`, `readiness`, `history` and `targets` commands, and `aic task run`, which takes it itself around state operations, so two `aic` processes no longer overwrite each other's state files. A command that cannot get the lock within 10 seconds changes nothing and exits 1 with `Error: another aic process is using the state files (waited 10s).` A command that only prints help takes no lock. The lock is released by the operating system when its holder dies. New commands lock until they are added to `READ_ONLY_COMMANDS`.
- Upgrade note: the first command that locks creates `.aic.lock` in the data directory. The file holds no data and can be ignored. Do not delete it while an `aic` command is running.
- `write_text_atomic` retries `os.replace` up to five times, 50 ms apart, after a `PermissionError`, which is how Windows reports a file that another process has open. Other errors are not retried.
- The CLI help text and the `pyproject.toml` description now read "Local-first deterministic control platform for AI work." They said "autonomous AI development and control platform", which no part of the project does (G8). The `autonomous-agents` keyword became `deterministic`.
- `aic task complete` and `aic task fail` take an optional `--reason "<text>"`. The reason is stored in the attempt record, printed, and shown by `aic task history`. A blank reason is refused before anything changes. Without `--reason` nothing changes, and the record's reason stays empty.
- The execution start result names the attempt it opened (`attempt_id`), and an `ExecutionOutcome` can carry one. The coordinator passes the attempt it started with every outcome. The recorder refuses an outcome whose attempt is no longer the task's open attempt, changes nothing, and gives the reason `attempt was superseded; the adapter reported <outcome>`. Before this, a run superseded by a requeue and a restart could close the newer attempt. Outcomes without an attempt ID behave as before.
- `ExecutionCoordinator` accepts an optional `state_guard`, a function that returns a context manager holding the state lock. The coordinator enters it around the start and around each outcome recording, and never while an adapter runs. Without a guard it behaves as before. Before this, eight coordinators run at once lost updates: several reported `completed` while one task was.
- Added `aic task run <task-id> --target <name>`, which runs a ready task through the execution coordinator and prints the task, the target, a result (`completed`, `failed` or `rejected`) and a reason. It exits 0 only for `completed`. `--target` is required. Added `aic task targets`, which lists the registered targets. The only target is `noop`, a new adapter in `execution/adapters.py` that completes the task without doing any work and says so in its reason. Adapters are registered in code, never loaded from configuration.
- `aic task run` is the first self-locking command. `main` does not hold the state lock for its whole run. The command takes it for the start and again for recording the outcome, and never while the adapter runs, so `aic task requeue` and every other command still work during a run. If the lock cannot be taken to record the outcome, the command says that the adapter has run, and the task is left `running` with its attempt open, the shape a crash leaves. `SELF_LOCKING_COMMANDS` in `cli.py` lists such commands, and the classification test checks all three classes.
- Added `ProcessAdapter` in `execution/process.py`, an adapter that runs a fixed command in a child process. AIC writes the request as one JSON object to the child's standard input and reads one JSON object from its standard output. A timeout, too much output, a non-zero exit, output that is not that object and an unknown outcome are failed outcomes with a reason. The child gets a short list of environment variables and runs in a new empty temporary directory. When a run times out, writes too much, or is interrupted, the child and the processes it started are stopped. Nothing registers a process adapter yet.
- `aic task run` now catches Ctrl-C. It prints `Interrupted.` and how to recover, and exits 130, instead of printing a traceback. No outcome is recorded, and the task stays `running` with its attempt open.
- Added the first stage of permissions. `ExecutionRequest` has a `requires_grant` field that defaults to true, and an adapter can declare `requires_grant`. An adapter that says nothing is treated as needing a grant. `noop` declares that it needs none, and `ProcessAdapter` needs one by default. Admission asks a grant source, in `execution/grants.py`, and a request that is not covered is refused with `target X is not granted for project Y` and writes nothing. The default source, `NoGrants`, allows nothing. The coordinator marks the request it gives to the starter from the adapter and not from the caller, and the adapter still receives the request as the caller sent it.
- Added the second stage of permissions. `PermissionRegistry`, in `permissions/registry.py`, keeps grants in `permissions.json` next to the task file, in the versioned format and with atomic writes. A grant has an ID, a project, a target, a reason, the time it was made and, once revoked, the time it was revoked. A revoked grant stays as history. A blank field, a second active grant for the same pair and a revoke with nothing active are refused, and a revoke ends every active grant for the pair. `aic task run` gives the registry to admission, so a target that needs a grant runs when an active grant covers its project and the target. A `permissions.json` that cannot be read stops the run with an error. `aic validate` reports a repeated grant ID, an active duplicate, and an active grant for an unregistered project or a target that the code does not register, and it still never writes. There is no `aic permission` command yet.

### Documentation

- Completed the README. It was truncated and ended inside an unclosed code block. Added a quick start, a command reference, and configuration.
- Added `docs/STATUS.md`: verified status, capability labels, known gaps, and invariants.
- Added `docs/DESIGN_DIRECTIONS.md`: research-stage design ideas, clearly separated from implemented behavior.
- Reconciled `docs/ARCHITECTURE.md` with the code: module map, goal derivation rules, task transition table, readiness check order, persistence, and execution entry points.
- Corrected the "no silent repair" wording. Validation is read-only; reconciliation, including `aic goal status`, persists derived goal status.
- Described Phase 2 in the roadmap as implemented at the library level, and added a proposed Phase 2.5 for boundary hardening.
- Extended `CONTRIBUTING.md` with environment setup, test isolation, and the working agreement.
- Documented current security-relevant gaps in `SECURITY.md`.
- Filled in `.env.example` and the pull request template, which were empty.
- Added `docs/RECOVERY_DESIGN.md`: a design for recovering tasks left in `running` (G5), with options and a recommendation. Its Option A is now implemented as `aic task requeue`.
- Added `docs/EXECUTION_RECORDS_DESIGN.md`: a design for recording execution attempts (start time, outcome and reason), with options and a recommendation. It was accepted and is now implemented.
- Added `docs/FILE_LOCKING_DESIGN.md`: a design for locking the state files, with the reproduced lost-update evidence, options and a recommendation. It was accepted and is now implemented.
- Filled in `CODE_OF_CONDUCT.md`, which was empty, with the Contributor Covenant 2.1 (G9).
- Added a private reporting channel to `SECURITY.md`: the "Report a vulnerability" button on the repository's Security tab.
- Added `docs/TRANSITION_LOG_DESIGN.md`: a design note on status history, with options and a recommendation. Option A was accepted and is implemented; a full transition log is deferred to the Phase 3 design.
- Added `docs/COORDINATOR_CLI_DESIGN.md`: a design note for reaching the coordinator from the CLI, with options and a recommendation. Its three stages are built.
- Added `docs/PROCESS_ADAPTERS_DESIGN.md`: a design note for running adapters out of process, with a timeout, an output cap and a way to stop the whole process tree, based on what happens today when an in-process adapter hangs or is interrupted. Its first two stages are built, after a check on Windows settled how to stop a process tree.
- Added `docs/PERMISSIONS_DESIGN.md`: a design note on which projects may use which execution targets, where that is enforced, and what it cannot protect against. Its first two stages, the check in admission and the grant registry with its validation, are built.
- Recorded gap G12 in `docs/STATUS.md`: coordinator outcomes are matched to a task rather than to an attempt, and the library takes no state lock. Both were reproduced with the real coordinator and a slow fake adapter, and both affect library callers only, because no CLI command reached the coordinator then.

### Known issues (documented, not fixed)

- The state lock is advisory and works only between `aic` processes. It does not protect against hand edits or sync tools, and is not reliable on network file systems.
- There is no history of status changes other than execution attempts (the rest of G4).
- The execution coordinator takes no state lock unless it is given a `state_guard` (G12). `aic task run` passes one. Other code that calls the library directly must pass its own.
- `noop` is the only registered adapter. It can mark a task `completed` when no work was done, and its reason says so. Permissions are only partly built, and it runs in the CLI process. A `ProcessAdapter` with a timeout and an output cap exists, but nothing registers one. Its limits are listed as G13 in `docs/STATUS.md`.
- Nothing can be granted from the CLI yet. The registry and the checks in `aic validate` are built, but the `aic permission` commands are not, so a target that needs a grant is refused. Only `noop` is registered, and it needs none, so the CLI behaves as before.
- Nothing detects a `running` task whose process has died. A person recovers it with `aic task requeue`, which cannot tell whether the process is really gone.
- An attempt record left open for a completed or failed task cannot be closed from the CLI, so `aic validate` keeps reporting it (G11 in `docs/STATUS.md`).

See `docs/STATUS.md` for details and reproduction steps.

## 0.1.0

### Foundation

- Added deterministic project lifecycle management.
- Added goal lifecycle management and reconciliation.
- Added task lifecycle management.
- Added persistent local project state.
- Added deterministic validation and command behavior.

### Readiness

- Added task readiness evaluation.
- Added explicit readiness reasons.
- Added a readiness boundary before execution.

### Execution

- Added execution request and result contracts.
- Added execution admission.
- Added execution start boundary.
- Added execution outcome recording.
- Added execution targets.
- Added execution adapter registry.
- Added execution coordination.
- Added execution adapter failure handling.
- Added execution outcome identity validation.
- Added handling for invalid execution adapter results.

The current release establishes deterministic control boundaries and does not provide unrestricted system execution.
