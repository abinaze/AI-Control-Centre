# Changelog

All notable changes to AI Control Centre are documented here.

## Unreleased

### Changed

- `aic task start` now evaluates task readiness and refuses to start a task that is not ready, for example when its parent goal is failed or completed. It reports the readiness reason instead of the generic invalid-transition error.
- `aic task ready` now refuses when the parent goal is missing, completed, failed, or has an invalid status.
- `TaskReadinessEvaluator.parent_goal_blocker` exposes the parent goal check, and `evaluate` now uses it.
- The project, goal, and task registries now write their JSON files atomically: a temporary file, a flush to disk, then a replace. A crash or error during a write no longer risks leaving a truncated state file.
- Added `aic_control_centre.storage.write_text_atomic`, the helper the registries use.

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

### Known issues (documented, not fixed)

- Goal project names are not validated against the project registry.
- JSON persistence has no file locking or schema version.
- A `running` task has no recovery path.

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
