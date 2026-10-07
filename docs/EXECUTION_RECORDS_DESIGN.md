# Design Note: Execution Records

**Status: Proposed.** Nothing in this note is implemented. It needs the maintainer's approval, or changes, before any code is written. It follows [RECOVERY_DESIGN.md](RECOVERY_DESIGN.md) and addresses what is still open in gap G5, and the missing transition history in gap G4, in [STATUS.md](STATUS.md).

## Problem

Two things the tool needs are not stored anywhere.

- **When an attempt started.** A task stores `created_at` and `updated_at`, and `updated_at` moves on every status change. Nothing says how long a task has been `running`, so nothing can tell a slow run from a dead one. A later timeout or detector would have no start time to compare against.
- **Why an attempt ended.** `ExecutionOutcome.reason` and the coordinator's failure reasons, such as "execution adapter failed: ...", are returned to the caller and then dropped, because the outcome recorder writes only the new status. The reason given to `aic task requeue` is printed and then lost. `aic task complete` and `aic task fail` take no reason at all.

There is also no attempt count. A task that was started, requeued and started again looks the same as one started once, and nothing shows that a requeue ever happened.

## Facts about the current code

Each item was checked by reading the code.

- A task stores `id`, `goal_id`, `title`, `description`, `status`, `created_at` and `updated_at`. There is no start time, owner or attempt count.
- The library has two routes that change a task into or out of `running`: `ExecutionStarter.start` (`ready` to `running`) and `ExecutionOutcomeRecorder.record` (`running` to `completed` or `failed`).
- The CLI lifecycle commands, including `aic task ready`, `start`, `complete`, `fail` and `requeue`, all go through one function, `transition_task_status`. It receives only a task ID and a new status, so it cannot tell `ready` from `requeue`.
- A rejected execution request changes nothing (INV-1), and tests assert that the task file is untouched.
- `write_text_atomic` protects one file at a time. Two state files cannot be written together, and there is no file locking (G4).
- `aic validate` is read-only (INV-7).
- `AppConfig` knows three state files: projects, goals and tasks.
- No existing test builds `ExecutionStarter`, `ExecutionOutcomeRecorder` or `ExecutionCoordinator` with default registries. Every test passes explicit registries under `tmp_path`.

## Requirements

1. Every attempt records when it started, whichever route started it: the CLI or the library.
2. Every attempt records how it ended, including the reason given to a requeue.
3. Task status stays the authority. Lifecycle, readiness, admission and goal derivation do not change.
4. No change to the shape of the project, goal or task files, so no schema version bump for them.
5. A crash between two writes must leave a state that is detectable and harmless. It must never hide a stuck task.
6. The CLI and the library must not be able to drift apart. Two routes to `running` with only one gated was the G1 defect.
7. A rejected request still changes nothing (INV-1).
8. Do not pretend to detect dead processes. Records give a detector its start time; they are not the detector.

## Options

**A. Attempt records in a new state file (recommended).** One record per attempt, opened when the task starts and closed when the attempt ends.

- Pro: gives exactly what is missing: a start time, an end reason, and an attempt history, including requeues.
- Pro: a new file, so the existing files and the existing schema version are untouched (requirement 4). An older version of the tool simply ignores the file.
- Con: task status and the record live in two files and cannot be written together. The write order below handles this, but it is only as good as its tests.
- Con: every route must remember to record. See the parity tests and the risks.

**B. An append-only transition log.** One event per status change: task, from, to, time, reason.

- Pro: generic. It would also serve goals and the planned event and workflow boundary.
- Con: an attempt is not a first-class thing. The start time, attempt number and outcome have to be derived by scanning events.
- Con: the tool only writes whole files atomically. A true append-only log needs a different write model, which belongs with the locking decision (G4).
- Compatible with A: attempt records could later become a view over events. Not recommended as the first step.

**C. New fields on the task.** Add `started_at`, an attempt count and a last reason to each task.

- Pro: the smallest change, with no second file and nothing to keep in step.
- Con: it changes the task file shape, so it needs schema version 2 and a migration, and a tool from before the change could no longer read a saved file.
- Con: it keeps only the latest attempt. The history of a retried task is overwritten, which is the problem being solved.
- The recovery note already chose not to do this for the requeue reason, and it applies equally here.

**D. Do nothing.** Reasons stay lost and no start time exists, so automatic detection can never be built. Rejected.

## Recommendation: Option A

**The file.** `executions.json` in the data directory, written with the existing helpers: `{"schema_version": 1, "executions": [...]}`. It is read with `read_state_items` and written with `serialize_state_items` and `write_text_atomic`, so a corrupt or newer-version file is refused and left untouched, as for the other files.

**The record.**

| Field | Meaning |
| --- | --- |
| `id` | A uuid4 string. |
| `task_id` | The task this attempt belongs to. |
| `source` | `cli` or `coordinator`: the route that started the attempt. |
| `target` | The execution target for `coordinator`; `null` for `cli`. |
| `started_at` | UTC ISO time the attempt was opened. |
| `ended_at` | `null` while the attempt is open. |
| `ended_as` | `null` while open, then `completed`, `failed`, `requeued` or `abandoned`. |
| `reason` | The outcome reason or the requeue reason. An empty string when none was given. |

The attempt number is not stored. It is the position of the record among that task's records, so it cannot disagree with them.

**When records change.**

- Starting a task (`aic task start`, or `ExecutionStarter`) opens a record.
- Completing or failing a task (`aic task complete`, `aic task fail`, or `ExecutionOutcomeRecorder`) closes it with the outcome and its reason.
- `aic task requeue` closes it as `requeued` with the reason that command now prints and loses.
- A rejected request writes nothing. Admission results are not recorded: an accepted request is shown by the record existing, and a rejected one changes nothing today (INV-1). This narrows the one-line description of Step 5 in [ROADMAP.md](../ROADMAP.md), which also lists the request and the admission result.

**Write order.** The two files are written one after the other. The order is chosen so that a crash between the writes can leave only one shape: an open record whose task is not `running`.

- Starting: write the open record first, then move the task to `running`. A crash between leaves an open record and a `ready` task.
- Finishing or requeueing: move the task first, then close the record. A crash between leaves a `completed`, `failed` or `ready` task and an open record.

The opposite orders are worse. Moving the task to `running` before opening a record can leave a `running` task with no start time, which is the stuck state this change exists to remove. Closing the record before the task moves can leave a `running` task whose record says it ended.

**Validation.** `aic validate` stays read-only and reports three things: an open record whose task is not `running`, more than one open record for a task, and a record whose task does not exist. It does not report a `running` task that has no open record, because tasks started before this change have none (question 1).

**Stale open records.** When a task is started it is `ready`, so any open record for it is stale by definition. That record is first closed as `abandoned`, and then a new one is opened. This is a deliberate write by a command that is already writing. Validation and reads never repair anything.

**One recording path.** The registry lives in `execution/records.py` (the package is `execution`, not `executions`) with `open_attempt`, `close_attempt` and `list_attempts`. The CLI commands and the two library classes all call it. By default the file sits beside the task registry's file, so an existing test that passes a task registry under `tmp_path` writes its records there too, and no existing test can reach the real data directory. A new field in `AppConfig` is not needed, which avoids another unused field (G7).

**A way to read it.** `aic task history <task-id>`, read-only: the attempts for a task, oldest first, with start time, end time, outcome and reason.

**What does not change.** Task statuses and transitions, readiness, admission, goal derivation, the project, goal and task files, and the schema version. Nothing detects a dead run yet. `aic task history` lets a person see how long a task has been running, and a later timeout would use `started_at`.

Tests it would need:

- The registry opens, closes and lists records, refuses a newer schema version or a corrupt file, and a failed save keeps the previous file (INV-9).
- Starting from the CLI and from the library each open a record. A rejected start writes nothing (INV-1).
- Complete and fail close the record with their reason, from both routes. A coordinator failure keeps its "execution adapter failed" reason.
- A requeue closes the record as `requeued` with the reason, and the next start opens attempt 2. `aic task history` shows both.
- A failed write of the record at start leaves the task unchanged. A failed write after the task moved leaves an open record, and the next start closes it as `abandoned`.
- `aic validate` reports each of the three cases, and passes for a `running` task that has no record.
- Parity: the CLI and the library produce records of the same shape for start, complete, fail and requeue.
- Running the suite does not create a state file in the default data directory.

## Risks

- **Two files, one crash window.** The write order above makes the failure harmless and detectable, but, as with atomic writes, it is covered only by simulated write failures, not by a real crash.
- **A route that forgets to record.** A future way to start a task that skips the recorder would leave a `running` task with no record, and validation is deliberately silent about that. Protection is the parity tests and review, not enforcement.
- **No locking.** Two processes can still overwrite each other (G4). If two start the same task at the same moment, each opens a record and the later one closes the earlier as `abandoned`. That shows the G4 race in the history. It does not prevent it.
- **Reasons are free text, stored as given.** That includes exception messages from adapters, which can contain sensitive details. The file is local and unencrypted. This should be stated in [SECURITY.md](../SECURITY.md) when it is built.
- **File growth.** Each attempt adds a record, and each change rewrites the whole file, as the other registries do. That is fine at current scale and belongs with the locking and append-only discussion later.
- **Downgrade.** An older version of the tool ignores the file and can change task status without writing records. Nothing is corrupted. The records for those attempts are missing or stale.

## Open questions for the maintainer

1. A task that is already `running` when this ships has no record. When it is later completed, failed or requeued, should the command write a closed record with `started_at` set to `null`? Recommendation: yes, so the attempt still appears in the history, and validation accepts the `null`.
2. Should a stale open record be closed as `abandoned` when the task is next started? Recommendation: yes, as described. The alternative is to report it and leave it, which leaves a permanent validation failure.
3. Should `aic task complete` and `aic task fail` take an optional `--reason`? Recommendation: yes, but as a separate small step after records exist. Until then those records have an empty reason.
4. Should rejected requests be recorded? Recommendation: no, for the INV-1 reason above.
5. Should the default file location sit beside the task registry's file, as proposed, or should `AppConfig` gain an `executions_file`? Recommendation: beside the task file, because it keeps every existing test isolated without new patching.

## After this decision

Once the note is approved, the build would go in small steps: the record registry and its tests; recording from the library; recording from the CLI, with the parity tests; validation; `aic task history`; and the documentation. The same care as the requeue change applies: no step may leave a route to `running` or out of it unrecorded. Execution timeouts and automatic detection come after that, as a separate design, using `started_at`. File locking and a transition log remain separate decisions.
