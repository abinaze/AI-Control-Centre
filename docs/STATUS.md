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

After the schema version change the suite has 238 tests. The maintainer ran the full suite on Windows under Git Bash before each of the eleven code commits in that change and again after the documentation commits; the final run at `df1cbbb` gave 238 passed.

After the project reference change the suite has 251 tests. The maintainer ran the full suite on Windows under Git Bash at commit `d064385`: 251 passed.

After the task requeue change the suite has 274 tests: the 251 above plus 23 new ones. The maintainer ran the full suite on Windows under Git Bash before each of the ten code commits in that change and again after the documentation commits; the final run at `db4bb41` gave 274 passed.

After the execution records change the suite has 371 tests: the 274 above plus 97 new ones. The maintainer ran the full suite on Windows under Git Bash before each of the 25 code and test commits in that change and again after the documentation commits; the final run at `5dc48c9` gave 371 passed.

After the cleanups for G7 and G10 the suite has 376 tests: the 371 above plus 5 new ones. The maintainer ran the full suite on Windows under Git Bash before each of the nine code and test commits in that change and again after the documentation commits; the final run at `ec8a162` gave 376 passed.

After the file locking change the suite has 396 tests: the 376 above plus 20 new ones. The maintainer ran the full suite on Windows under Git Bash before each of the seven code and test commits in that change and again after the documentation commits; the final run at `2aa560a` gave 396 passed. On the same machine, a standalone check of the Windows lock (`msvcrt.locking`) passed under Python 3.14.3: a second process could not take a held lock, the lock was free after its holder was killed, and eight processes making 100 locked increments each reached 800 of 800 (3 of 800 without the lock). 12 parallel `aic task create` commands stored all 12 tasks. A writing command that could not get the lock stopped after about 10 seconds with exit status 1 and wrote nothing, while a read-only command ran at once.

After the G8 wording fix the suite has 398 tests: the 396 above plus 2 new ones. The maintainer ran the full suite on Windows under Git Bash before each of the three code and test commits in that change and again after the documentation commits; the final run at `aec67f7` gave 398 passed.

After the finishing reason change the suite has 413 tests: the 398 above plus 15 new ones. The maintainer ran the full suite on Windows under Git Bash before each of the four code and test commits in that change and again after the documentation commits; the final run at `622a424` gave 413 passed.

After the attempt identity change the suite has 425 tests: the 413 above plus 12 new ones. The maintainer ran the full suite on Windows under Git Bash before each of the six code and test commits in that change and again after the documentation commits; the final run at `56ca375` gave 425 passed.

After the coordinator state guard change the suite has 433 tests: the 425 above plus 8 new ones. The maintainer ran the full suite on Windows under Git Bash before each of the three code and test commits in that change and again after the documentation commits; the final run at `a5e6068` gave 433 passed.

After the coordinator CLI the suite has 448 tests: the 433 above plus 15 new ones. The maintainer ran the full suite on Windows under Git Bash before each of the five code and test commits in that change and again after the documentation commits; the final run at `181a322` gave 448 passed.

After the process adapter change the suite has 480 tests: the 448 above plus 32 new ones. The maintainer ran the full suite on Windows under Git Bash before each of the five code and test commits in that change and again after the documentation commits; the final run at `9151a5e` gave 479 passed and 1 skipped. The skipped test is the one that applies only to Linux. The process adapter's own tests ran on Windows, including the ones that stop a real process tree with `taskkill /F /T`. A separate check, `check_kill.py`, passed on the same machine under Python 3.14.3, and its results are in [PROCESS_ADAPTERS_DESIGN.md](PROCESS_ADAPTERS_DESIGN.md).

After the permission check the suite has 501 tests: the 480 above plus 21 new ones. The maintainer ran the full suite on Windows under Git Bash before each of the seven code and test commits in that change and again after the documentation commits; the final run at `b231165` gave 500 passed and 1 skipped. The skipped test is the one that applies only to Linux.

After the grant registry the suite has 568 tests: the 501 above plus 67 new ones. The maintainer ran the full suite on Windows under Git Bash before each of the ten code and test commits in that change and again after the documentation commits; the final run at `8b8f396` gave 567 passed and 1 skipped. The skipped test is the one that applies only to Linux.

After the permission commands the suite has 609 tests: the 568 above plus 41 new ones. The maintainer ran the full suite on Windows under Git Bash before each of the six code and test commits in that change and again after the documentation commits; the final run at `6efd6f6` gave 608 passed and 1 skipped. The skipped test is the one that applies only to Linux.

After `aic task running` the suite has 679 tests: the 609 above plus 70 new ones. The maintainer ran the full suite on Windows under Git Bash before each of the five code and test commits in that change and again after the documentation commits; the final run at `6b19333` gave 678 passed and 1 skipped. The skipped test is the one that applies only to Linux.

After the time checks in `aic validate` the suite has 728 tests: the 679 above plus 49 new ones. The maintainer ran the full suite on Windows under Git Bash before each of the six code and test commits in that change and again after the documentation commits; the final run at `955a618` gave 727 passed and 1 skipped. The skipped test is the one that applies only to Linux.

After unique project names the suite has 745 tests: the 728 above plus 17 new ones. The maintainer ran the full suite on Windows under Git Bash before each of the five code and test commits in that change and again after the documentation commits; the final run at `8937be0` gave 744 passed and 1 skipped. The skipped test is the one that applies only to Linux.

After the project directory check the suite has 790 tests: the 745 above plus 45 new ones.

## Capability status

| Area | Status | Notes |
| --- | --- | --- |
| Project registry | Implemented | `aic project add`, `aic project list`. A project name belongs to one directory: `aic project add` refuses a second directory with a name that is already registered, because goals and grants identify a project by its name. `aic validate` reports a registered directory that is deleted later (G15) |
| Goal registry and lifecycle | Implemented | Goal status is derived from task status |
| Task registry and lifecycle | Implemented | `pending → ready → running → completed \| failed`; a stuck `running` task returns to `ready` only through `aic task requeue` |
| Goal/task validation | Implemented | `aic validate`; does not write, and runs under the state lock. It also reports a time that cannot be read (G14) a project name that more than one directory has, and a registered project directory that does not exist or is not a directory (G15) |
| State file locking | Implemented | One exclusive lock per CLI command, on `.aic.lock` in the data directory; advisory, local disks only. See [FILE_LOCKING_DESIGN.md](FILE_LOCKING_DESIGN.md) |
| Task readiness | Implemented | `aic task readiness` |
| Task requeue | Implemented | `aic task requeue <task-id> --reason "<text>"`; the reason is printed and stored in the attempt record |
| Running task report | Implemented | `aic task running` lists the running tasks, longest first, with the route, the start time and how long each has been running, and `--older-than` takes a number and one of s, m, h or d. A task with no open attempt is timed from its last update and marked as an estimate. It is advisory: it cannot tell a live run from a dead one, and it writes nothing |
| Execution request/result contracts | Implemented | Used by `aic task run` |
| Execution admission | Implemented | Used by `aic task run`. It checks readiness, then, for a target that acts on a project's files, that the project is registered and its directory exists, then the grant |
| Execution start | Implemented | Used by `aic task run` |
| Execution outcome recording | Implemented | Used by `aic task run` |
| Execution adapter registry | Implemented | Used by `aic task run` and `aic task targets`; adapters are registered in code |
| Execution coordinator | Implemented | Reached from the CLI by `aic task run`, with the state lock held only around state operations |
| Execution adapters | Implemented | One registered adapter, `noop`, which completes a task without doing any work. No adapter does real work |
| Execution grants | Implemented | A request that needs a grant is refused unless an active grant covers the project of its task and the target. `aic permission grant`, `revoke` and `list` manage the grants in `permissions.json`, `aic task targets` shows which targets need one, and `aic validate` checks the grants. A grant says which projects may use a target. It does not limit what the target touches, and the CLI cannot tell a person from a program |
| Process adapter | Implemented (library) | `ProcessAdapter` runs a fixed command in a child process with a timeout, an output cap, a minimal environment, and the whole process tree stopped on a timeout or an interrupt. Nothing registers one yet. See G13 for its limits |
| Concrete execution adapters | Planned | None exist; only test doubles |
| Execution records: registry, library recording, and CLI recording | Implemented | `ExecutionRecordRegistry` in `executions.json`, next to the task file. `ExecutionStarter` and `aic task start` open an attempt record before the task moves to `running`. `ExecutionOutcomeRecorder`, `aic task complete`, `aic task fail` and `aic task requeue` close it after the task moves, with the outcome and its reason. `aic task complete` and `aic task fail` take an optional `--reason "<text>"`; a blank one is refused before anything changes |
| Execution record validation and history | Implemented | `aic validate` checks the records and stays read-only. `aic task history <task-id>` lists a task's attempts, oldest first. The design is in [EXECUTION_RECORDS_DESIGN.md](EXECUTION_RECORDS_DESIGN.md) |
| Task dependencies | Planned | Tasks belong to a goal; no task-to-task links |
| Event / workflow boundary | Planned | |
| Evidence | Planned | |
| What an adapter may touch, CPU and memory limits | Planned | Grants decide which projects may use a target. They do not limit what a target touches |
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

### G3. Goal project names were not validated (closed)

**Closed.** `aic goal create` now refuses a project that is not registered, and `aic validate` reports goals whose project is not registered. Names are matched exactly, so `Aircursor` and `aircursor` are different projects. The rest of this entry records the original defect.

Original defect: `aic goal create "..." --project does-not-exist` succeeded with exit 0, although the help text says "Registered project name". `aic validate` did not check goal-to-project references, so goals linked to projects by free-text name only.

Goals created before this change that point at an unregistered project are not modified. `aic validate` reports them until the project is registered with `aic project add <path>`.

### G4. Persistence has no history (source; mostly closed)

**Mostly closed.** All three registries now write through `write_text_atomic`: the text goes to a temporary file in the same directory, is flushed to disk, and then replaces the state file with `os.replace`. A crash or error during a write leaves the previous file intact. The rest of this entry records what is still open.

**Schema version.** Each state file is now a JSON object with a `schema_version` number and its items under `projects`, `goals`, or `tasks`. Files written before versioning are a bare list and are read as version 1; they are rewritten in the versioned shape the next time the tool saves them, and reading never rewrites them. A file with a newer version than the tool supports, a file that is not valid JSON, and a file with an unusable shape are refused with an error and left untouched.

**File locking.** Every `aic` command except a short read-only list now runs under one exclusive lock on `.aic.lock` in the data directory, held for the whole command, so two `aic` processes no longer overwrite each other's changes. A process that cannot get the lock within 10 seconds changes nothing and exits 1 with `Error: another aic process is using the state files (waited 10s).` The operating system releases the lock when its holder dies, so a killed process does not leave the tool locked. `write_text_atomic` also retries `os.replace` a few times after a `PermissionError`, which is how Windows reports a file that another process has open. Lost updates were reproduced before this change with real processes: 12 parallel `aic task create` commands all reported success, 10 of the tasks were lost, and `aic validate` still passed. With the lock, the same 12 commands, and 40, stored every task in the Linux sandbox. The design and the evidence are in [FILE_LOCKING_DESIGN.md](FILE_LOCKING_DESIGN.md).

Still open: there is no transition history, only the history of execution attempts that `aic task history` shows. An attempt can carry the reason given to `aic task complete --reason` or `aic task fail --reason`. The maintainer accepted keeping the attempt history and deferring a full transition log to the Phase 3 design; the options and the decision are in [TRANSITION_LOG_DESIGN.md](TRANSITION_LOG_DESIGN.md). Still unrecorded: when a task became ready, and a goal's earlier statuses. The lock is advisory: it keeps `aic` processes apart, and does nothing about a person editing a state file by hand or a sync tool that copies it. It is not reliable on network file systems. The execution coordinator, which is library code, takes no lock itself; the coordinator CLI planned for Phase 3 must take it around state operations only, never while an adapter runs. A hard kill during a write can leave a stale `.<file>.<id>.tmp` file, which the registries ignore.

### G5. A `running` task had no recovery path (reproduced; closed for the operator path, with automatic detection still open)

**Closed for the operator path.** `aic task requeue <task-id> --reason "<text>"` moves a `running` task back to `ready` without failing its goal. The task then goes through `aic task start` and readiness like any other. The command requires a reason, refuses a task that is not `running`, and refuses a task whose parent goal is missing, completed, failed, or has an invalid status. See [RECOVERY_DESIGN.md](RECOVERY_DESIGN.md) (accepted, Option A) and [ROADMAP.md](../ROADMAP.md), Phase 2.5, Step 4. The rest of this entry records the original defect and what is still open.

Original defect: the transition table allowed `running → completed | failed` only. If a process dies after a task is started but before an outcome is recorded, the task stays `running` with nothing to time it out or recover it. Reproduced with the CLI: the only ways out of a dead `running` task were a false `aic task complete` or an `aic task fail` that fails the whole goal, after which nothing in that goal can run again.

Still open:

- Nothing detects a dead process. A person has to decide that a `running` task is dead. If its process is in fact alive, requeueing and starting it again runs the task twice.
- A requeue and its reason are stored in the attempt record, and `aic task history <task-id>` shows them. Nothing acts on the recorded start time: no timeout or detector uses it, and `aic task running` only reports it.
- `aic task complete` on a dead task is still accepted, so a false success can still be recorded.
- `aic task running` lists the running tasks and how long each has been running, longest first, with an optional `--older-than` filter, as designed in [STALE_TASKS_DESIGN.md](STALE_TASKS_DESIGN.md). It helps a person to decide what to requeue. It does not detect a dead run, because a live run and a killed run leave identical records. Detection needs a recorded owner or lease, which is left to the first real adapter.

### G6. The coordinator is unreachable from the CLI (closed; only a noop adapter exists)

`aic --help` used to expose `doctor`, `validate`, `project`, `goal`, and `task` only. Nothing registered an adapter or invoked `ExecutionCoordinator`, and no concrete adapter existed. Now `aic task run <task-id> --target <name>` runs a ready task through the coordinator, and `aic task targets` lists the targets. The only target is `noop`, which completes the task without doing any work, so no real work can be run from the CLI yet. Permissions are built for targets: the check is in admission and reads the grant registry, and `aic permission grant` makes a grant. A grant does not limit what a target touches. The only registered adapter, `noop`, needs none and runs inside the CLI process. Permissions are in [PERMISSIONS_DESIGN.md](PERMISSIONS_DESIGN.md) (all four stages built). The design, with the options that were weighed, is in [COORDINATOR_CLI_DESIGN.md](COORDINATOR_CLI_DESIGN.md). A process adapter, which runs an adapter out of process with a timeout and an output cap, is built and described in [PROCESS_ADAPTERS_DESIGN.md](PROCESS_ADAPTERS_DESIGN.md); nothing registers one yet.

### G7. Unused configuration and scattered version string (partly closed)

`AppConfig.state_dir` was removed, because no module read it and nothing created the directory. `AppConfig.default_model_provider` stays on purpose: it is documented as a reserved setting (`AIC_DEFAULT_MODEL_PROVIDER` in the README and `.env.example`) for the later model layer, and no module reads it yet.

The version `0.1.0` is now written in two places, `pyproject.toml` and `aic_control_centre/__init__.py`. The `--version` output reads the package value, and a test fails if the two disagree. Making `pyproject.toml` read the version from the package was not done, because it changes packaging.

### G8. Wording tension about autonomy (closed)

The `pyproject.toml` description and the CLI help text both said "autonomous AI development and control platform", while the README, SECURITY, and ARCHITECTURE documents state that no autonomous behavior exists. Both now read "Local-first deterministic control platform for AI work.", and the `autonomous-agents` keyword in `pyproject.toml` became `deterministic`. `test_pyproject_description_matches_the_cli_description` keeps the two descriptions identical, and `test_metadata_makes_no_claim_of_autonomy` fails if the word returns to the description or the keywords.

### G9. Empty files in the repository (closed)

`.env.example`, `CODE_OF_CONDUCT.md`, and `.github/pull_request_template.md` were zero bytes and are now filled in. `CODE_OF_CONDUCT.md` is the Contributor Covenant, version 2.1. Reports go to the maintainer through the contact options on their GitHub profile.

### G10. Duplicated constant (closed)

`KNOWN_GOAL_STATUSES` is now defined once, in `goals/model.py`, and imported by `readiness/tasks.py` and `validation/goal_tasks.py`. A test requires both modules to use that same object, and another requires the set to match the `GOAL_STATUS_` constants, so a new status cannot be added to one place only.

### G11. An attempt left open for a finished task cannot be closed from the CLI (reproduced)

When `aic task complete`, `aic task fail` or `aic task requeue` runs, the task moves first and its attempt record is closed afterwards. If the records file cannot be written at that moment, for example because it is unreadable, the command prints an error and exits with status 1 after the task has already moved. For `complete` and `fail` the task is then terminal and nothing starts it again, so nothing closes the attempt. `aic validate` reports the open record on every run, and `aic task history` flags it. Reproduced with the CLI by corrupting `executions.json` between `aic task start` and `aic task complete`.

A task that is `ready` again after a crash does not have this problem. A failed close during `requeue`, or a crash between opening a record and moving the task, leaves a `ready` task, and the next `aic task start` closes the leftover record as `abandoned`.

Until a fix is chosen, the record can be closed by hand: in `executions.json`, set the record's `ended_at` to a UTC time and its `ended_as` to `abandoned`. The likely fix is a small explicit command that does the same. It is not built, and it is a maintainer decision because it adds a write path outside the normal lifecycle.

### G12. The coordinator library takes no state lock by default (closed in the library; reproduced, library only)

Nothing in the CLI reaches the coordinator (G6), so these affect only code that calls the library directly, and the coordinator CLI that Phase 3 would add. Both were reproduced by running the real `ExecutionCoordinator` with a slow fake adapter.

Superseded runs (closed): while the adapter was running, a person ran `aic task requeue` and then `aic task start` on the same task. When the adapter finished, the recorder accepted its result because the task was `running` again, and it closed the person's second attempt as `completed` with the adapter's reason. The coordinator reported `completed`. Now the start result names the attempt it opened, the coordinator passes that ID with every outcome, and the recorder refuses an outcome whose attempt is no longer the task's open attempt (INV-21). The refusal changes nothing, and the coordinator reports `rejected` with what the adapter reported. Running the same scenario again against the real CLI, the person's attempt stayed open, the task stayed `running`, and `aic validate` passed.

No lock: only `main` takes the state lock, not the library. Eight coordinators run at once on eight different tasks lost updates. In three runs, 3, 4 and 4 coordinators reported `completed`, but exactly one task ended `completed` each time, five to seven stayed `ready`, and `aic validate` reported open records whose task was `ready`.

Closed in the library: `ExecutionCoordinator` takes an optional `state_guard`, a function that returns a context manager holding the state lock. It enters the guard around the start and around each outcome recording, and never while an adapter runs (INV-22). With the real lock as the guard, the same eight coordinators, run three times, all reported `completed`, all eight tasks ended `completed`, all eight records were closed, and `aic validate` passed. During a six-second adapter run, `aic project add` and `aic task requeue` each finished in under a tenth of a second.

`aic task run` passes the guard (INV-23). Eight `aic task run` processes at once all exited 0, all eight tasks ended `completed`, all eight records were closed, and `aic validate` passed.

Still open: a coordinator built without a guard still takes no lock, so any other caller of the library that runs more than one process must pass one.

### G13. A process adapter cannot stop everything in some cases (documented limits)

The process adapter stops the child and the processes it started when a run times out, writes too much output, or is interrupted. It has known limits. Nothing registers a process adapter yet, so none of them affects the CLI today.

- If AIC itself is killed hard, the child and its tree keep running until they end. The task is left `running` with its attempt open, which is the safe crash shape. A Windows job object with kill-on-close would stop them. It was not built, because a child can start its own children before it is assigned to the job.
- After a normal exit, processes that the child left behind are stopped on Linux, where the child's process group outlives it. On Windows nothing is done after a normal exit, because the tree is stopped only while the child is alive.
- A process left behind that holds the output pipe open does not hang the adapter. It is left running.
- `taskkill /F /T` stops the tree as it exists when it runs, so a process started at that moment could escape.
- CPU and memory limits are not enforced. The defaults, 60 seconds, 1 MiB of output and 64 KiB of error output, are guesses and are set per target in code.

### G14. Times were not validated (closed)

**Closed.** `aic validate` now reports a `created_at`, `updated_at`, `started_at`, `ended_at`, `granted_at` or `revoked_at` that cannot be read as ISO 8601 text with an offset, and the validation fails. Goals and tasks are always checked. Execution records and grants are checked when their registries are given, which `aic validate` always does. A time that may be empty is allowed to be empty: the end of an open attempt, the start of a closed record from before start times were stored, and the revoke time of an active grant. A time with no offset, such as a bare date, is unreadable because it cannot be compared with the clock. This is the rule that `aic task running` uses, and both now read times through `read_time` in `timestamps.py`. A bad time is not refused when the state is loaded, because that would stop every command, including the ones that are used to recover and the listing that shows the task. The rest of this entry records the original defect.

Original defect: neither the task model nor the execution record model checked that a time is a time, and `aic validate` did not check it either. An `ExecutionRecord` accepted `started_at="garbage"`, and with that start time in `executions.json`, `aic validate` printed `Validation passed.` Reproduced with the real CLI. After the change, a state with `started_at` set to `garbage` and a task `updated_at` of `2026-10-19` printed `Validation failed.` with one line for each, exited 1 and changed no file, and `aic task running` still listed the task, with the start time shown as unreadable.

### G15. Project names were not unique, and a deleted project directory was not noticed (closed)

**Closed.** Both halves are fixed. `aic project add` refuses a directory whose name another registered directory already has, names the path that holds it and writes nothing, and `aic validate` reports a name that more than one directory has, which also covers a state that was written before the change. `aic validate` also reports a registered directory that does not exist or is not a directory, and `aic task run` refuses a target that acts on a project's files when its project is not registered or its directory is not usable, before the adapter runs and before anything is written (see [FIRST_ADAPTER_DESIGN.md](FIRST_ADAPTER_DESIGN.md), stages 1 and 2). The directory can still vanish after that check and before the adapter's work, so an adapter has to handle that itself. The rest of this entry records the original defect and what each change did.

Original defect: two different directories with the same last name, both called `app`, were registered with `aic project add`. Both were accepted and listed, `aic validate` passed, and a lookup by name returned the first. Goals and grants identify a project by its name only, so a grant for `app` did not say which directory it covered. Reproduced with the real CLI on Linux.

After the names change, the second `aic project add` printed `Error: a project named app is already registered at <path>` and two lines of advice, exited 1 and wrote nothing. A state with two directories named `app`, written by hand, printed `Validation failed.` with one line that names both paths, exited 1 and left `projects.json` unchanged. There is no command to remove a project, so a state that already has two directories under one name is repaired by removing one entry from `projects.json`. With one entry removed from such a state, `aic validate` printed `Validation passed.`

The deleted-directory half was reproduced on Linux after the names change: with a registered directory removed, `aic validate` printed `Validation passed.` and `aic project list` still showed the project. After the second change, `aic validate` printed `Validation failed.` and `Project directory does not exist: other (<path>)` and exited 1, and putting the directory back made it print `Validation passed.` again. `aic project list` still lists the project, because it only lists. A target that needs a project, run after its directory was deleted or replaced by a file, was rejected with the reason, left the task `ready` and wrote no execution record. The `noop` target was not affected.

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
| INV-12 | A goal is created only for a registered project. | Yes, in `create_goal` | `test_create_goal_rejects_unregistered_project`, `test_create_goal_matches_project_names_exactly`, `test_main_goal_create_rejects_unregistered_project` |
| INV-13 | Validation reports every goal whose project is not registered when the validator is given a project registry; `aic validate` always gives it one. | Yes, in `GoalTaskValidator` | `test_goal_for_unregistered_project_is_reported`, `test_every_goal_with_an_unregistered_project_is_reported`, `test_main_validate_reports_goal_for_unregistered_project` |
| INV-14 | Only a `running` task can be requeued, only while its parent goal is open, and requeueing never changes a goal to a closed status. | Yes, in `requeue_task`; the transition table keeps `completed` and `failed` terminal | `test_requeue_task_refuses_task_that_is_not_running`, `test_requeue_task_rejects_task_in_closed_goal`, `test_requeue_task_keeps_goal_in_progress`, `test_registry_still_rejects_failed_to_ready` |
| INV-15 | In the CLI, `aic task ready` never moves a `running` task back to `ready`. Only `aic task requeue`, with a reason, does. The library call `TaskRegistry.update_task_status` does allow the edge, and no library code calls it. | Yes, in `mark_task_ready` and `requeue_task` | `test_mark_task_ready_refuses_running_task`, `test_requeue_task_requires_a_reason`, `test_task_requeue_requires_a_reason`, `test_stuck_running_task_can_be_requeued_and_finished` |
| INV-16 | Every start opens an attempt record before the task moves to `running`, and every end closes it after the task moves, from the CLI and from the library. A crash between the two writes leaves an open record for a task that is not `running`, never a `running` task whose record says it ended. | Yes, in `ExecutionStarter.start`, `ExecutionOutcomeRecorder.record`, `start_task`, `_finish_task` and `requeue_task` | `test_failed_attempt_write_leaves_the_task_ready`, `test_failed_task_update_leaves_an_open_attempt`, `test_failed_record_write_leaves_an_open_attempt`, `test_start_task_failed_record_write_keeps_task_ready`, `test_start_task_crash_after_record_leaves_an_open_attempt`, `test_failed_close_leaves_the_task_moved_and_attempt_open`, `test_failed_requeue_close_leaves_the_task_ready_and_attempt_open` |
| INV-17 | The CLI and the library record attempts with the same shape. Only `source` and `target` differ. | Only by tests | `test_cli_and_library_record_an_attempt_alike`, `test_only_the_route_and_target_differ_between_routes`, `test_cli_and_library_abandon_a_stale_attempt_alike` |
| INV-18 | A rejected request or a refused command writes no attempt record. | Yes, because recording happens only after the checks pass | `test_rejected_start_writes_no_attempt_record`, `test_rejected_outcome_writes_no_record`, `test_coordinator_writes_no_record_for_an_unknown_target`, `test_start_task_refused_writes_no_record`, `test_refused_finish_writes_no_record`, `test_refused_requeue_of_a_ready_task_writes_no_record` |
| INV-19 | `aic validate` reports an open record whose task is not `running`, more than one open record for a task, a record whose task does not exist, and a repeated record ID, without writing any file. A `running` task with no record is accepted. | Yes, in `GoalTaskValidator` | `test_open_record_for_a_task_that_is_not_running_is_reported`, `test_two_open_records_for_a_task_are_reported`, `test_record_for_a_missing_task_is_reported`, `test_duplicate_execution_record_ids_are_reported`, `test_running_task_without_a_record_is_valid`, `test_validation_does_not_modify_the_records_file` |
| INV-20 | Every CLI command takes the state lock for its whole run, except the read-only list (`doctor`, `project list`, `goal list`, `permission list`, and `task list`, `status`, `readiness`, `history`, `targets` and `running`) and the self-locking list (`task run`). `aic validate` locks. A command that cannot get the lock within the timeout changes nothing and exits 1. A command added later locks until it is classified. | Yes, in `main`, through `_needs_state_lock` | `test_every_parser_command_is_classified`, `test_only_read_only_commands_skip_the_lock`, `test_writing_command_fails_cleanly_while_the_lock_is_held`, `test_validate_waits_for_the_lock`, `test_read_only_command_runs_while_the_lock_is_held`, `test_concurrent_commands_lose_no_tasks`, `test_targets_runs_while_the_lock_is_held` |
| INV-21 | An outcome that names an attempt is applied only if that attempt is still the task's open attempt. Otherwise nothing changes and the outcome is refused as superseded. The coordinator names the attempt it started with every outcome, including the outcomes it builds for adapter errors. | Yes, in `ExecutionOutcomeRecorder.record` | `test_outcome_naming_the_open_attempt_is_recorded`, `test_outcome_for_a_superseded_attempt_is_refused`, `test_outcome_naming_an_attempt_needs_an_open_attempt`, `test_start_result_names_the_attempt_it_opened`, `test_late_outcome_does_not_change_a_newer_attempt` |
| INV-22 | A coordinator that has a state guard enters it around the start and around each outcome recording, and never while an adapter runs. A coordinator without a guard takes no lock. | Yes, in `ExecutionCoordinator` | `test_guard_covers_the_start_and_the_outcome_but_not_the_adapter`, `test_guard_covers_a_refused_start`, `test_guard_is_not_entered_for_an_unknown_target`, `test_state_lock_is_free_while_the_adapter_runs`, `test_concurrent_coordinators_lose_no_updates` |
| INV-23 | A self-locking command takes the state lock around each state operation and never while it runs something slow. `aic task run` holds it for the start and again for recording the outcome, and not while the adapter runs. If the lock cannot be taken to record the outcome, the task is left `running` with its attempt open, which is the shape a crash leaves, and the command says so. | Yes, in `run_task`, through the coordinator's state guard | `test_requeue_works_while_the_adapter_runs`, `test_run_fails_cleanly_while_the_lock_is_held`, `test_run_keeps_the_task_running_if_the_outcome_cannot_be_recorded`, `test_concurrent_runs_complete_every_task` |
| INV-24 | A process adapter runs a fixed command in a child process and stops that child and the processes it started when the run takes too long, writes too much, or is interrupted. A timeout or too much output is a failed outcome with a reason. | Yes, in `ProcessAdapter` | `test_a_child_that_runs_too_long_is_stopped_and_fails`, `test_timeout_stops_the_whole_process_tree`, `test_output_over_the_limit_is_stopped_and_fails`, `test_an_interrupt_stops_the_process_tree`, `test_a_process_left_holding_the_output_does_not_hang_the_adapter`, `test_a_timed_out_run_fails_the_task_and_records_why` |
| INV-25 | Nothing from a task reaches a child's command line or environment. The command is fixed in code, the request travels as JSON on standard input, and the child inherits only a short list of environment variables. | Yes, in `ProcessAdapter` and `child_environment` | `test_the_child_gets_only_the_allowed_environment`, `test_child_environment_keeps_only_listed_names`, `test_valid_outcome_is_returned_and_the_request_reaches_the_child` |
| INV-26 | A request that needs a grant is admitted only if an active grant covers the project of its task and its target. Otherwise it is refused, nothing is written, and the reason names the target and the project. A request needs a grant by default, an adapter that says nothing needs one, and the coordinator marks the request from the adapter and not from the caller. | Yes, in `ExecutionAdmission` and `ExecutionCoordinator` | `test_a_request_is_refused_when_no_grant_covers_it`, `test_a_grant_for_the_project_and_target_allows_the_request`, `test_a_grant_for_another_project_does_not_allow_it`, `test_admission_with_no_grant_source_refuses_by_default`, `test_a_refused_start_writes_nothing`, `test_the_coordinator_rejects_a_target_that_is_not_granted`, `test_coordinator_sends_the_request_marked_by_the_adapter`, `test_the_adapter_decides_not_the_caller` |
| INV-27 | A grant is made only for a registered project and a registered target, with a reason, and a pair that already has an active grant is not granted again. A refused grant writes nothing. | Yes, in `grant_permission` and `PermissionRegistry.grant` | `test_grant_refuses_an_unregistered_project`, `test_grant_refuses_an_unregistered_target`, `test_grant_refuses_a_blank_argument`, `test_grant_refuses_a_pair_that_is_already_granted`, `test_a_grant_with_a_blank_field_is_refused_and_writes_nothing`, `test_an_active_duplicate_is_refused` |
| INV-28 | A revoked grant allows nothing and stays in the file as history. A revoke ends every active grant for the pair, and it works even when the project or the target is no longer registered. | Yes, in `PermissionRegistry.revoke` and `revoke_permission` | `test_revoke_ends_the_grant_and_keeps_the_record`, `test_revoke_ends_every_active_grant_for_the_pair`, `test_a_revoked_pair_can_be_granted_again`, `test_a_grant_can_be_revoked_after_its_project_or_target_is_gone`, `test_run_is_refused_again_after_a_revoke` |
| INV-29 | A grants file that cannot be read is an error and never counts as no grants. A run, a validation, a grant, a revoke or a listing that meets one stops with an error, and the commands leave the file as it was. | Yes, in `PermissionRegistry`, through `read_state_items` | `test_a_newer_schema_version_is_refused`, `test_an_invalid_grant_in_the_file_is_an_error`, `test_an_unreadable_grants_file_stops_the_run`, `test_an_unreadable_grants_file_stops_validation`, `test_validate_reports_an_unreadable_grants_file`, `test_an_unreadable_grants_file_is_reported_not_overwritten` |
| INV-30 | `aic validate` reports a repeated grant ID, an active grant that repeats another, and an active grant for a project or a target that does not exist, and it never writes. | Yes, in `GoalTaskValidator` | `test_a_repeated_grant_id_is_reported`, `test_an_active_duplicate_is_reported`, `test_a_grant_for_an_unregistered_project_is_reported`, `test_a_grant_for_an_unregistered_target_is_reported`, `test_validation_does_not_modify_the_grants_file`, `test_validate_does_not_create_the_grants_file` |
| INV-31 | `aic permission grant` and `revoke` take the state lock for the whole command, and `aic permission list` does not. Concurrent grants lose none. | Yes, in `main`, through `_needs_state_lock` | `test_every_parser_command_is_classified`, `test_grant_and_revoke_wait_for_the_lock_and_change_nothing`, `test_list_runs_while_the_lock_is_held`, `test_eight_grants_at_once_lose_none` |
| INV-32 | `aic task running` only reports. It writes nothing, takes no lock, and never requeues, fails or completes a task. | Yes, because it is in `READ_ONLY_COMMANDS` and the report only reads | `test_describing_never_writes`, `test_the_command_never_modifies_the_state_files`, `test_the_command_runs_while_the_lock_is_held`, `test_every_parser_command_is_classified`, `test_only_read_only_commands_skip_the_lock` |
| INV-33 | A running task is never hidden by bad data. A start time that cannot be read is listed and kept by `--older-than`, a start time in the future is listed as such and is not counted as long, and a task is timed from its latest open attempt, or from its last update when it has none, with the estimate labelled. | Yes, in `describe_running_tasks`, `filter_older_than` and `show_running_tasks` | `test_a_start_time_that_cannot_be_used_is_flagged`, `test_older_than_keeps_unreadable_and_drops_future_times`, `test_a_start_time_in_the_future_is_flagged_and_counts_as_zero`, `test_a_start_time_that_cannot_be_read_is_shown_and_kept_by_the_filter`, `test_the_latest_open_attempt_is_used_and_closed_ones_are_not`, `test_a_task_with_no_open_attempt_is_timed_from_its_last_update`, `test_a_task_with_no_attempt_is_marked_as_an_estimate` |
| INV-34 | `aic validate` reports every time that cannot be read as ISO 8601 text with an offset, in goals and tasks and in the records and grants that it checks, and the validation fails. A time that the model allows to be empty is not an error when it is empty. | Yes, in `GoalTaskValidator`, through `read_time` | `test_a_goal_time_that_cannot_be_read_is_reported`, `test_a_task_time_that_cannot_be_read_is_reported`, `test_a_record_time_that_cannot_be_read_is_reported`, `test_a_grant_time_that_cannot_be_read_is_reported`, `test_a_time_with_no_offset_or_no_text_is_reported`, `test_an_open_attempt_may_have_no_end_time`, `test_a_closed_legacy_attempt_may_have_no_start_time`, `test_an_active_grant_may_have_no_revoke_time`, `test_a_start_time_that_is_not_a_time_fails_validation`, `test_text_that_is_not_a_usable_time_is_unreadable` |
| INV-35 | A project name belongs to one directory. `aic project add` refuses a directory whose name another registered directory already has, names the path that holds it and writes nothing. The same directory added again is registered once, and names are compared exactly. `aic validate` reports every name that more than one directory has, once for each name, and never writes. | Yes, in `ProjectRegistry.add_project` and `GoalTaskValidator._project_name_errors` | `test_a_second_directory_with_the_same_name_is_refused`, `test_a_refused_project_changes_nothing`, `test_the_command_reports_the_clash_and_says_how_to_go_on`, `test_the_cli_refuses_the_second_project`, `test_names_are_compared_exactly`, `test_the_same_directory_is_still_registered_once`, `test_a_name_used_by_two_directories_is_reported`, `test_every_shared_name_is_reported`, `test_validation_does_not_modify_the_projects_file`, `test_aic_validate_fails_on_a_shared_project_name` |
| INV-36 | A request for a target that acts on a project's files is admitted only if the project of its task is registered and its directory exists and is a directory. Otherwise it is refused, nothing is written, and the reason names the project. The check comes after readiness and before the grant check, runs at every request, and does not apply to a target that needs no project, such as `noop`. | Yes, in `ExecutionAdmission._project_directory`, with `requires_project` set by the coordinator from the adapter | `test_a_project_that_is_not_registered_is_refused`, `test_a_directory_that_is_gone_is_refused`, `test_a_path_that_is_a_file_is_refused`, `test_a_directory_that_cannot_be_read_is_refused`, `test_the_directory_is_checked_at_every_request`, `test_admission_with_no_project_source_refuses_by_default`, `test_a_request_that_needs_no_project_is_not_looked_up`, `test_the_project_is_checked_before_the_grant`, `test_a_refused_project_runs_nothing_and_writes_nothing`, `test_noop_is_not_affected_by_a_missing_project`, `test_run_is_refused_when_the_directory_is_gone`, `test_run_is_refused_when_the_path_is_a_file`, `test_run_is_refused_when_the_project_is_not_registered`, `test_noop_still_runs_when_the_directory_is_gone` |
| INV-37 | An adapter that needs a project is given the path that the project registry holds, and only that. A path set by a caller is never passed on, an adapter that needs no project receives none, and a process child receives the path only in the JSON on its standard input, not in its command, its environment or its working directory. | Yes, in `ExecutionCoordinator.coordinate` and `ProcessAdapter.execute` | `test_the_adapter_is_given_the_registered_path`, `test_a_path_set_by_the_caller_is_not_used`, `test_a_path_set_by_the_caller_is_not_passed_to_another_adapter`, `test_the_adapter_decides_whether_a_project_is_needed`, `test_an_adapter_that_needs_a_project_sends_the_path`, `test_the_path_is_not_in_the_command_or_the_environment`, `test_an_adapter_that_needs_no_project_sends_no_path`, `test_an_adapter_that_needs_a_project_fails_without_a_path`, `test_run_gives_the_adapter_the_registered_path`, `test_a_child_process_receives_the_path_on_standard_input` |
| INV-38 | `aic validate` reports every registered project whose directory does not exist, is not a directory or cannot be looked at, with the project name and the path, and it never writes or creates the directory. | Yes, in `GoalTaskValidator._project_directory_errors` | `test_a_project_whose_directory_is_gone_is_reported`, `test_a_project_whose_path_is_a_file_is_reported`, `test_every_missing_directory_is_reported`, `test_a_directory_that_cannot_be_read_is_reported`, `test_directories_are_not_checked_without_a_project_registry`, `test_validation_does_not_create_the_missing_directory`, `test_aic_validate_fails_on_a_missing_project_directory`, `test_aic_validate_passes_when_the_directory_is_back` |

Two invariants proposed in the research notes have nothing to enforce yet because the subsystems do not exist: "unauthorized tools cannot execute" (there are no tools yet; INV-26 covers execution targets) and "unverified cognitive knowledge cannot override policy" (no cognitive layer).

## Recommended next milestone

G1, G3 and G5 are closed, and G4 is mostly closed: only the transition history remains. G5 is closed for the operator path only; automatic detection of dead runs is still open, and `aic task running` only helps a person to decide. Execution records and file locking are built, and G11 is open. The remaining hardening step is in [ROADMAP.md](../ROADMAP.md), Phase 2.5: the rest of G4, which is a transition log.

Recommended next: decide what to do about G11, either a small explicit command that closes an attempt left open for a finished task or accepting the manual edit, and then design a transition log as part of Phase 3, which is the rest of G4; the decision to defer it is in [TRANSITION_LOG_DESIGN.md](TRANSITION_LOG_DESIGN.md). The coordinator CLI is built as stage 3 of [COORDINATOR_CLI_DESIGN.md](COORDINATOR_CLI_DESIGN.md), with a `noop` adapter only. The process adapter is built as stages 1 and 2 of [PROCESS_ADAPTERS_DESIGN.md](PROCESS_ADAPTERS_DESIGN.md), and nothing registers one yet. The permissions work in [PERMISSIONS_DESIGN.md](PERMISSIONS_DESIGN.md) is built, in four stages. The listing of how long tasks have been `running` is built as `aic task running` ([STALE_TASKS_DESIGN.md](STALE_TASKS_DESIGN.md)). The first real adapter is designed in [FIRST_ADAPTER_DESIGN.md](FIRST_ADAPTER_DESIGN.md), which says how the project path reaches it, where it runs and what it may touch, because a grant does not limit that. The maintainer accepted its recommendations, and its first two stages are built: project names are unique, and a target that acts on a project's files gets the registered path and is refused when its project is not registered or its directory is not usable, which closes G15. The next stage is the read-only check, a wrapper that compares a snapshot of the project before and after a run. No real adapter should be built before the stages that follow. Timeouts and automatic detection of dead runs use the recorded start time and belong with the adapter and limits work in Phase 3, as a separate design.
