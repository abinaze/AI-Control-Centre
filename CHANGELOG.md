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
- Added `aic_control_centre.locking.state_lock`, an exclusive operating system lock on `.aic.lock` in the data directory. `main` holds it for the whole of every command except `doctor` and the `list`, `status`, `readiness` and `history` commands, so two `aic` processes no longer overwrite each other's state files. A command that cannot get the lock within 10 seconds changes nothing and exits 1 with `Error: another aic process is using the state files (waited 10s).` A command that only prints help takes no lock. The lock is released by the operating system when its holder dies. New commands lock until they are added to `READ_ONLY_COMMANDS`.
- Upgrade note: the first command that locks creates `.aic.lock` in the data directory. The file holds no data and can be ignored. Do not delete it while an `aic` command is running.
- `write_text_atomic` retries `os.replace` up to five times, 50 ms apart, after a `PermissionError`, which is how Windows reports a file that another process has open. Other errors are not retried.
- The CLI help text and the `pyproject.toml` description now read "Local-first deterministic control platform for AI work." They said "autonomous AI development and control platform", which no part of the project does (G8). The `autonomous-agents` keyword became `deterministic`.
- `aic task complete` and `aic task fail` take an optional `--reason "<text>"`. The reason is stored in the attempt record, printed, and shown by `aic task history`. A blank reason is refused before anything changes. Without `--reason` nothing changes, and the record's reason stays empty.

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
- Added `docs/COORDINATOR_CLI_DESIGN.md`: a proposed design note for reaching the coordinator from the CLI, with options and a recommendation. Nothing is implemented.
- Recorded gap G12 in `docs/STATUS.md`: coordinator outcomes are matched to a task rather than to an attempt, and the library takes no state lock. Both were reproduced with the real coordinator and a slow fake adapter, and both affect library callers only, because no CLI command reaches the coordinator.

### Known issues (documented, not fixed)

- The state lock is advisory and works only between `aic` processes. It does not protect against hand edits or sync tools, and is not reliable on network file systems.
- There is no history of status changes other than execution attempts (the rest of G4).
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
