# Project Status

This is the verified handover snapshot for AI Control Centre. It separates what is **implemented** from what is only planned or researched, and it records the known gaps between documented intent and actual behavior.

Keep this file honest. Update it whenever a milestone lands. If a statement here stops matching the code, the statement is wrong.

## Status labels

| Label | Meaning |
| --- | --- |
| **Implemented** | Code and passing tests exist in this snapshot. |
| **Designed** | A boundary has a written contract, but no code yet. |
| **Planned** | Listed in [ROADMAP.md](../ROADMAP.md); not started. |
| **Research** | Exploratory ideas in [DESIGN_DIRECTIONS.md](DESIGN_DIRECTIONS.md); no commitment. |

## Snapshot provenance

- Commit: `4ea03cf` (`docs: document project architecture and workflow`), the HEAD of `main`. The maintainer confirmed with `git log` and `git status` that `main` was in sync with `origin/main` and the working tree was clean.
- The source-level checks below were run on a GitHub archive of that commit. The archive contained no `.git` directory, so they were not run inside the repository itself.
- Verified with Python 3.12.3 and pytest 9.1.1 on Linux. Those checks did not cover the project's primary environment; the maintainer's Windows run is recorded under Verification results.

## Verification results

| Check | Result |
| --- | --- |
| `python -m pytest -q` | 180 passed |
| `python -m compileall -q src` | OK |
| Whitespace, CRLF, tab, and final-newline scan of `.py`, `.md`, `.toml` | Clean |
| Test isolation | Running the suite does not create the default user data directory |

These results are for commit `4ea03cf`. After the G1 fix the suite has 196 tests, all passing in the same environment.

The maintainer ran the suite on Windows under Git Bash at commit `00e3582` (after the G1 fix): 196 passed.

After the atomic write change the suite has 208 tests. The maintainer ran the full suite on Windows under Git Bash before each of the eight commits in that change; at `2481490` it gave 208 passed. Those runs include replacing an existing state file with `os.replace` on Windows.

After the schema version change the suite has 238 tests, all passing on Linux.

## Capability status

| Area | Status | Notes |
| --- | --- | --- |
| Project registry | Implemented | `aic project add`, `aic project list` |
| Goal registry and lifecycle | Implemented | Goal status is derived from task status |
| Task registry and lifecycle | Implemented | `pending → ready → running → completed \| failed` |
| Goal/task validation | Implemented | `aic validate`; read-only |
| Task readiness | Implemented | `aic task readiness` |
| Execution request/result contracts | Implemented | Library only |
| Execution admission | Implemented | Library only |
| Execution start | Implemented | Library only |
| Execution outcome recording | Implemented | Library only |
| Execution adapter registry | Implemented | Library only |
| Execution coordinator | Implemented | Library only; no CLI command invokes it |
| Concrete execution adapters | Planned | None exist; only test doubles |
| Execution records / history | Planned | Only `created_at` / `updated_at` are stored |
| Task dependencies | Planned | Tasks belong to a goal; no task-to-task links |
| Event / workflow boundary | Planned | |
| Evidence | Planned | |
| Permissions, limits, timeouts | Planned | |
| Cognitive layer (NeuroIntelligence) | Research | See [DESIGN_DIRECTIONS.md](DESIGN_DIRECTIONS.md) |
| Memory layers | Research | |
| Policy and approval | Research | |
| Tool registry, agent registry, model interface | Research | |
| Planner | Research | |
| LLM, shell, browser, Git, GitHub execution | Not started | Intentionally deferred |

## Known gaps

Each item below was checked against the code. Items marked **reproduced** were confirmed by running the real CLI; items marked **source** were confirmed by reading the code.

### G1. Two routes to `running`; only one was gated (closed)

**Closed.** `aic task start` now evaluates readiness and refuses when the task is not ready. `aic task ready` refuses when the parent goal is missing, completed, failed, or has an invalid status. See [ROADMAP.md](../ROADMAP.md), Phase 2.5, Step 1. The rest of this entry records the original defect.

`ExecutionStarter` (library) runs readiness and admission before moving a task to `running`. The CLI commands `aic task ready`, `aic task start`, `aic task complete`, and `aic task fail` call `TaskRegistry.update_task_status` directly and do not consult readiness or admission.

Reproduction before the fix: create a goal with two tasks, drive the first to `failed` (the goal becomes `failed`), then use the second task.

```text
aic task readiness <task-b>   ->  Ready: no   Reason: parent goal is failed   (exit 1)
aic task ready <task-b>       ->  succeeds    (exit 0)
aic task start <task-b>       ->  succeeds    (exit 0)   task is now "running"
aic validate                  ->  Validation passed.
```

No test pinned this behavior, so it was an unspecified design gap, not a documented decision. See INV-4 below.

### G2. `aic goal status` writes state (reproduced; intentional and tested)

`aic goal status` reconciles the goal and persists the derived status. With a deliberately wrong persisted goal status, `aic validate` reported the mismatch without changing anything, then `aic goal status` rewrote `goals.json`, after which `aic validate` passed.

This behavior is pinned by `test_show_goal_status_reconciles_tasks`, so it is intentional. Earlier documentation described the principle as "no silent repair" without this exception. The documentation now states the actual rule; see [ARCHITECTURE.md](ARCHITECTURE.md).

### G3. Goal project names are not validated (reproduced)

`aic goal create "..." --project does-not-exist` succeeds with exit 0, although the help text says "Registered project name". `aic validate` does not check goal-to-project references. Goals therefore link to projects by free-text name only.

### G4. Persistence has no locking or history (source; mostly closed)

**Mostly closed.** All three registries now write through `write_text_atomic`: the text goes to a temporary file in the same directory, is flushed to disk, and then replaces the state file with `os.replace`. A crash or error during a write leaves the previous file intact. The rest of this entry records what is still open.

**Schema version.** Each state file is now a JSON object with a `schema_version` number and its items under `projects`, `goals`, or `tasks`. Files written before versioning are a bare list and are read as version 1; they are rewritten in the versioned shape the next time the tool saves them, and reading never rewrites them. A file with a newer version than the tool supports, a file that is not valid JSON, and a file with an unusable shape are refused with an error and left untouched.

Still open: there is no file locking, so two concurrent processes can overwrite each other's changes; and there is no transition history. A hard kill during a write can leave a stale `.<file>.<id>.tmp` file, which the registries ignore. On Windows the replace can fail if another process has the state file open; the previous file is then left intact. That failure is covered by a simulated error in the tests but has not been exercised with a real second process. This is acceptable for a single-user alpha but must be addressed before concurrency or durable execution.

### G5. A `running` task has no recovery path (source)

The transition table allows `running → completed | failed` only. If a process dies after a task is started but before an outcome is recorded, the task stays `running` with nothing to time it out or recover it. Recovery and timeouts are listed as future work in [ARCHITECTURE.md](ARCHITECTURE.md).

### G6. The coordinator is unreachable from the CLI (reproduced)

`aic --help` exposes `doctor`, `validate`, `project`, `goal`, and `task` only. Nothing registers an adapter or invokes `ExecutionCoordinator`, and no concrete adapter exists. The execution pipeline is exercised only by tests.

### G7. Unused configuration and scattered version string (source)

`AppConfig.state_dir` and `AppConfig.default_model_provider` are defined and populated but no module reads them. The version `0.1.0` is written in three places: `pyproject.toml`, `aic_control_centre/__init__.py`, and the `--version` string in `cli.py`.

### G8. Wording tension about autonomy (source)

The `pyproject.toml` description and the CLI help text both say "autonomous AI development and control platform". The README, SECURITY, and ARCHITECTURE documents state that no autonomous behavior exists. These strings were left unchanged in the documentation pass because they live in code and metadata.

### G9. Empty files in the repository (source)

`.env.example`, `CODE_OF_CONDUCT.md`, and `.github/pull_request_template.md` were zero bytes. `.env.example` and the pull request template are now filled in. `CODE_OF_CONDUCT.md` is still empty and needs a decision on which code of conduct to adopt.

### G10. Duplicated constant (source)

`KNOWN_GOAL_STATUSES` is defined separately in `readiness/tasks.py` and `validation/goal_tasks.py`. The two currently match. A future status addition could update only one.

## Invariants

These are the architectural rules the project is converging on. The table shows which are actually enforced.

| ID | Invariant | Enforced in code | Test evidence |
| --- | --- | --- | --- |
| INV-1 | A rejected execution request must not mutate task state. | Yes, at admission, start, and coordinator | `test_pending_task_is_not_started` (status and `updated_at` unchanged), `test_admission_does_not_modify_persisted_task_file`, `test_coordinator_does_not_execute_rejected_task` |
| INV-2 | Only `running` tasks may record an execution outcome. | Yes, in `ExecutionOutcomeRecorder` | `test_pending_task_cannot_record_outcome`, `test_ready_task_cannot_record_outcome`, `test_missing_task_cannot_record_outcome` |
| INV-3 | `completed` and `failed` tasks cannot transition further. | Yes, via `TASK_STATUS_TRANSITIONS` in the registry | `test_invalid_task_status_transitions`, `test_registry_rejects_invalid_status_transition` |
| INV-4 | A task enters `running` only if readiness passes. | Yes, on the `ExecutionStarter` path and on `aic task start` | `test_start_task_rejects_task_in_closed_goal`, `test_start_task_rejects_pending_task`, `test_failed_goal_blocks_remaining_tasks_from_cli_lifecycle` |
| INV-5 | An unknown execution target never starts a task. | Yes, the coordinator resolves the target first | `test_coordinator_rejects_unknown_execution_target_without_starting` |
| INV-6 | Adapter failures never bypass outcome recording. | Yes, exception, wrong-task, and invalid-result cases | Coordinator tests for each case |
| INV-7 | Validation never modifies persisted state. | By construction: the validator only calls `list_*` methods | No dedicated non-mutation test |
| INV-8 | A task is marked `ready` only while its parent goal is open. | Yes, in `aic task ready` | `test_mark_task_ready_rejects_task_in_closed_goal`, `test_mark_task_ready_rejects_task_with_missing_goal` |
| INV-9 | A failed write of a state file leaves the previous file intact. | Yes, via `write_text_atomic` in all three registries | `test_failed_replace_keeps_original_and_cleans_up`, `test_failed_save_keeps_existing_registry_file`, `test_registry_failed_status_update_keeps_existing_status` |
| INV-10 | A state file written by a newer schema version, or one that is malformed, is refused and left unmodified. | Yes, in `read_state_items`; every registry read goes through it | `test_read_state_items_refuses_newer_schema_version`, `test_read_state_items_rejects_malformed_files`, `test_registry_refuses_newer_schema_version` |
| INV-11 | Loading a state file never rewrites it, including a legacy file. Commands that save, such as `aic goal status`, do write (see G2). | Yes, loads only parse the file; only saves write | `test_read_state_items_does_not_modify_the_file`, `test_registry_reads_legacy_list_file_without_rewriting_it` |

Two invariants proposed in the research notes have nothing to enforce yet because the subsystems do not exist: "unauthorized tools cannot execute" (no tools or permissions) and "unverified cognitive knowledge cannot override policy" (no cognitive layer).

## Recommended next milestone

G1 is closed, and G4 is mostly closed: only file locking and transition history remain. The open hardening steps are in [ROADMAP.md](../ROADMAP.md), Phase 2.5: project reference validation (G3), the recovery path for `running` tasks (G5), execution records, and the remainder of G4.

Recommended next: G3. It is small and finishes the validation rules before execution records are added. It needs one decision first: whether a goal must reference a project that is registered. Execution records can then be added as a new versioned state file from the start.
