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
- Added the second stage of permissions. `PermissionRegistry`, in `permissions/registry.py`, keeps grants in `permissions.json` next to the task file, in the versioned format and with atomic writes. A grant has an ID, a project, a target, a reason, the time it was made and, once revoked, the time it was revoked. A revoked grant stays as history. A blank field, a second active grant for the same pair and a revoke with nothing active are refused, and a revoke ends every active grant for the pair. `aic task run` gives the registry to admission, so a target that needs a grant runs when an active grant covers its project and the target. A `permissions.json` that cannot be read stops the run with an error. `aic validate` reports a repeated grant ID, an active duplicate, and an active grant for an unregistered project or a target that the code does not register, and it still never writes.
- Added the last stages of permissions. `aic permission grant <project> --target <name> --reason "<text>"` lets a registered project use a registered target, `aic permission revoke <project> --target <name>` ends the grant, and `aic permission list [--all]` shows the grants that are active, or all of them. A project or a target that is not registered, a blank reason and a pair that is already granted are refused. A grant can be revoked even if its project or its target is no longer registered. Granting a target that needs no grant, such as `noop`, is allowed and says that it changes nothing. `grant` and `revoke` take the state lock and `list` does not. `aic task targets` now says whether each target needs a grant. No command asks for confirmation, because the CLI cannot tell a person from a program.
- Added `aic task running [--older-than <duration>]`, a read-only listing of the running tasks and how long each has been running, longest first. A task is timed from its latest open attempt, or from its last update with an estimate label when it has none. `--older-than` takes a whole number and one of `s`, `m`, `h` or `d`. A start time that cannot be read is listed as unknown and kept by the filter, and a start time in the future is listed and not counted as long. The command is advisory: it cannot tell a live run from a dead one, because they leave identical records. It writes nothing and takes no lock.
- Added time checks to `aic validate`. A `created_at`, `updated_at`, `started_at`, `ended_at`, `granted_at` or `revoked_at` that cannot be read as ISO 8601 text with an offset is reported, and the validation fails. Goals and tasks are always checked, and execution records and grants are checked as before when their registries are given. A time that may be empty is not an error when it is empty. Times are read through one function, `read_time` in the new `timestamps.py`, which `aic task running` now uses as well. A bad time is reported and not refused when the state is loaded.
- `aic project add` now refuses a second directory with a name that is already registered. It names the path that holds the name, exits 1 and writes nothing, because goals and grants identify a project by its name. Registering the same directory again still returns the project that exists, and names are compared exactly. `ProjectRegistry.add_project` raises the new `ProjectNameInUseError`.
- `aic validate` now reports a project name that more than one directory has, once for each name, with the paths. Upgrade note: a state that already has two directories under one name is not modified, but `aic validate` fails until one entry is removed from `projects.json` by hand, because there is no command to remove a project. This is the names half of G15.
- `aic validate` now also reports a registered project whose directory does not exist, whose path is not a directory or that cannot be looked at, with the project name and the path, and it neither writes nor creates the directory. Upgrade note: a state in which a registered directory has been deleted now fails validation until the directory is put back, because there is no command to remove a project. This is the deleted-directory half of G15.
- Added `requires_project` and `project_path` to `ExecutionRequest`, and `project_path` to the admission and start results. An adapter can declare `requires_project`. For a request that needs a project, admission refuses a project that is not registered, a directory that does not exist, a path that is not a directory and a directory that cannot be looked at, before the grant check and without writing anything, and the coordinator gives the adapter the registered path. A path that a caller sets is never passed on. `noop`, and every adapter that does not declare `requires_project`, is not affected. `aic task run` gives admission the project registry. Added `ProjectSource` and `NoProjects` in `execution/projects.py`.
- `ProcessAdapter` takes `requires_project`. When it is set, the path is sent as `project_path` in the JSON on the child's standard input and only there, and the adapter fails without starting the child when the request has no path.
- Added `execution/snapshot.py` with `take_snapshot`, `compare_snapshots` and `escape_name`. A snapshot lists every file with its size, modification time and SHA-256, every directory and every link. A link, including a Windows junction, is recorded and never followed, a file that is not a regular file is never opened, and what cannot be read is recorded as unreadable.
- Added `ReadOnlyAdapter` in `execution/readonly.py`. It wraps an adapter, takes a snapshot of the project before and after the run, and turns a run that changed anything in the project into a failed outcome that starts `the project changed during a read-only run`. It detects a change and does not prevent one. Nothing registers it yet, so no behaviour changes.
- Fixed the project directory check. It no longer uses `Path.exists()` and `Path.is_dir()`, which answer no for any error on some Python versions, so a directory that could not be looked at could be reported as missing. `projects/directory.py` asks the system once with `os.stat` and tells a directory that is not there from a path that is not a directory and from one that cannot be read. An unreadable directory is now refused by `aic task run` and reported by `aic validate` with the reason that the system gave, for example `cannot be read: <path>; Access is denied`.
- Fixed the registries reading a state file that could not be read as an empty registry, which would have let the next save overwrite what was saved. `read_state_items_or_empty` in `storage.py` returns an empty list only when there is no file. Any other error is a `StateFileError` that names the file and the reason, so the CLI prints `Error: ...` and exits 1. The plain `read_state_items` reports an unreadable file the same way instead of a traceback.
- Added `inspect_directory` and `describe` in `execution/inspect_project.py`. The walk uses directory listings and file status only, never opens a file and never follows a link, counts files, directories, links, other entries and unreadable entries, adds up the size of the files, keeps the three largest and notes a README and a `.git` at the top level. The result is one short reason with names that are escaped and cut.
- Added the child process entry point to the same module, `python -m aic_control_centre.execution.inspect_project`. It reads the request from standard input and always answers with one JSON line and exit status 0, with a failed outcome for a request that is not UTF-8 or JSON, has no project path, or names a directory that is missing, is not a directory or cannot be read.
- Registered the `inspect` target in `build_adapter_registry`: a `ReadOnlyAdapter` around a `ProcessAdapter` that runs that module with `sys.executable`, with a grant and a project required. `aic task targets` now lists two targets. AIC has to be installed for the child to start (G19).
- Changed two tests that assumed `noop` was the only shipped adapter, so that they pass before and after the registration, and added a test that every shipped adapter other than `noop` needs a grant.

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
- Added `docs/PERMISSIONS_DESIGN.md`: a design note on which projects may use which execution targets, where that is enforced, and what it cannot protect against. All four of its stages are built.
- Added the invariants INV-27 to INV-31 for grants to `docs/STATUS.md`, and moved the Execution grants row to Implemented.
- Added `docs/STALE_TASKS_DESIGN.md`: a design note for a read-only listing of how long each task has been `running`, based on what a live run and a killed run leave on disk. It is implemented as `aic task running`.
- Added the invariants INV-32 and INV-33 and the gap G14 (times are not validated) to `docs/STATUS.md`.
- Closed the gap G14 in `docs/STATUS.md` and added the invariant INV-34 for the time checks.
- Added `docs/FIRST_ADAPTER_DESIGN.md`: a design note for the first adapter that does real work on a project, based on what a process child can see and reach, how project names and paths behave, and what a snapshot of a project costs. Its first three stages, unique project names, the project path in the request with its check in admission, and the read-only check as a wrapper, are built.
- Recorded the Windows observations in `docs/FIRST_ADAPTER_DESIGN.md`: paths with spaces and non-ASCII characters round-trip, a child can reach any path that the user can, a snapshot of 2,175 files took 0.28 seconds to list and 0.62 seconds to hash, and modification times advance in coarse steps, which points to comparing content hashes.
- Added the gap G15 (project names are not unique, and a deleted project directory is not noticed) to `docs/STATUS.md`.
- Marked `docs/FIRST_ADAPTER_DESIGN.md` accepted as recommended with its first stage built, added the invariant INV-35 for unique project names to `docs/STATUS.md`, and narrowed G15 to the deleted directory.
- Marked stages 1 and 2 of `docs/FIRST_ADAPTER_DESIGN.md` built, with a section on each, added the invariants INV-36 to INV-38 to `docs/STATUS.md`, and closed G15.
- Marked stage 3 of `docs/FIRST_ADAPTER_DESIGN.md` built, with a section on it and the Windows observations of a junction, added the invariants INV-39 and INV-40 and the gap G16 to `docs/STATUS.md`, and added the rule for read-only adapters to the contributing guide.
- Marked stage 4 of `docs/FIRST_ADAPTER_DESIGN.md` built, with a section on it and its Windows record, added the invariants INV-43 to INV-46 and the gap G19 to `docs/STATUS.md`, updated the architecture, the security policy, the roadmap and the readme for `inspect`, and added the rules for modules that run out of process and for tests that need a link to the contributing guide.
- Recorded the run of `inspect` on Windows through the real CLI, and the full suite at `873c106`, in `docs/FIRST_ADAPTER_DESIGN.md` and `docs/STATUS.md`.
- Recorded the failure on Windows that was not explained as G17 and the state file fix as G18 in `docs/STATUS.md`, added the invariants INV-41 and INV-42, noted the failure in the first adapter design note, and added the rule about `Path.exists()` to the contributing guide.
- Recorded gap G12 in `docs/STATUS.md`: coordinator outcomes are matched to a task rather than to an attempt, and the library takes no state lock. Both were reproduced with the real coordinator and a slow fake adapter, and both affect library callers only, because no CLI command reached the coordinator then.

### Known issues (documented, not fixed)

- The state lock is advisory and works only between `aic` processes. It does not protect against hand edits or sync tools, and is not reliable on network file systems.
- There is no history of status changes other than execution attempts (the rest of G4).
- The execution coordinator takes no state lock unless it is given a `state_guard` (G12). `aic task run` passes one. Other code that calls the library directly must pass its own.
- `noop` is the only registered adapter. It can mark a task `completed` when no work was done, and its reason says so. A grant does not limit what an adapter touches, and it runs in the CLI process. A `ProcessAdapter` with a timeout and an output cap exists, but nothing registers one. Its limits are listed as G13 in `docs/STATUS.md`.
- A grant says which projects may use a target. It does not limit what the target touches. The CLI cannot tell a person from a program, so grants are a policy for automation and not a defence against a process that runs as the same operating system user. Only `noop` is registered, and it needs no grant.
- Nothing detects a `running` task whose process has died. A person recovers it with `aic task requeue`, which cannot tell whether the process is really gone. `aic task running` shows how long each `running` task has been running, to help a person to decide.
- A project directory can still vanish between the admission check and the adapter's work. The check is made once, so an adapter that acts on a project has to treat that as a failed outcome. `inspect` acts on a project, and it treats a directory that has vanished as a failed outcome.
- The read-only check detects a change after a run and does not prevent it, sees only the project, and its snapshots are not limited in time or in the number of files (G16). `inspect` is wrapped in it.
- `inspect` runs a module of AIC in a child process that gets no `PYTHONPATH`, so AIC has to be installed for the Python that runs it (G19).
- One test failed once on Windows, and the cause is not known. It did not happen again in 25 runs of that test on its own, 50 runs of the same steps through the real CLI and two full runs. The check that printed the message was changed so that a recurrence says why (G17).
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
