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
- Added `aic task requeue <task-id> --reason "<text>"`. It returns a `running` task to `ready`, so a task whose process died can be retried through readiness without failing its goal. A reason is required. The command refuses a task that is not `running` and a task whose parent goal is missing, completed, failed, or has an invalid status. It does not start the task and never changes a goal to a closed status. The reason is printed but not stored.
- The task transition table now allows `running → ready`. `aic task ready` refuses a `running` task and points to `aic task requeue`, so the new edge is reached only through requeue.

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

### Known issues (documented, not fixed)

- JSON persistence has no file locking.
- Nothing detects a `running` task whose process has died. A person recovers it with `aic task requeue`, which cannot tell whether the process is really gone.
- The reason given to `aic task requeue` is printed but not stored.

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
