# Design Note: Transition Log

**Status: Proposed.** Nothing in this note is implemented. It needs the maintainer's decision before any code is written. It addresses the second half of gap G4 in [STATUS.md](STATUS.md). The first half, file locking, is built; see [FILE_LOCKING_DESIGN.md](FILE_LOCKING_DESIGN.md).

## Problem

A task and a goal each store one status and one `updated_at` time. When the status changes, the old status and the time it was set are overwritten. The execution records ([EXECUTION_RECORDS_DESIGN.md](EXECUTION_RECORDS_DESIGN.md)) keep the history of runs, but they do not cover every status change.

This was checked on the current code (Linux sandbox). One task was taken through `aic project add`, `goal create`, `task create`, `task ready`, `task start`, `task requeue --reason "worker died"`, `task start` and `task fail`. Then `aic task status`, `aic task history` and the state files were read. Here is what they can and cannot answer:

| Question | Can the stored state answer it? |
| --- | --- |
| When was the task created? | Yes. `created_at`. |
| When did the task become ready, and again after the requeue? | No. Both times are gone. |
| How many runs were there, and when did each start and end? | Yes. `aic task history` shows two attempts. |
| Why was the first run requeued? | Yes. The history shows "worker died". |
| Why did the second run fail? | No. `aic task fail` takes no reason, so the record's reason is empty. |
| When did the task fail? | Yes. The end of attempt 2, and `updated_at`. |
| What statuses did the goal pass through, and when? | No. Only the last change survives, as the goal's `updated_at`. |

A gap in history is not damage. Nothing in the state is wrong. The question is whether the missing answers matter enough to build for.

## Facts about the current code

Each item was checked by reading the code or by running it.

- Every task status change ends in `TaskRegistry.update_task_status`, which stores the new status and a new `updated_at` and keeps nothing about the previous status. The CLI reaches it through `transition_task_status`. The library reaches it through `ExecutionStarter` and `ExecutionOutcomeRecorder`.
- Goal status is derived from task statuses by `GoalTaskOrchestrator.reconcile_goal`, which runs after each task change and in `aic goal status` (G2). A goal's history therefore follows from its tasks' history.
- Attempt records cover `ready` to `running` (the record opens) and the four ways an attempt ends: `completed`, `failed`, `requeued` and `abandoned`. They do not cover creation, which has `created_at`, or `pending` to `ready`.
- `ExecutionRecordRegistry.close_attempt` already accepts a reason. `aic task requeue` supplies one, and so does the coordinator's outcome path, which keeps adapter failure reasons. `aic task complete` and `aic task fail` supply none.
- The execution records note answered its open question about `--reason` for `complete` and `fail`: yes, as a separate small step after records exist. That step was not built.
- Every command that writes already runs under the state lock (INV-20), writes files atomically, and keeps attempt records in the order INV-16 requires.
- A second history file would be a fourth file written by one command, next to `executions.json`, `tasks.json` and `goals.json`. Files are written one at a time, so a crash between two writes is possible.

## Requirements

Any answer must keep these.

1. History never claims more than was recorded. It is local and not tamper-evident, like the attempt records, and the documents must say so.
2. A crash leaves at most one detectable shape, as INV-16 does for attempt records.
3. `aic validate` stays read-only.
4. Existing file shapes stay as they are unless there is a strong reason. Schema version 2 would be a one-way change: code from before it cannot read upgraded files.
5. Standard library only, on Windows and Linux, under the state lock.
6. Nothing here pre-decides Phase 3. Who may approve a task, what identity means and which permissions exist will decide which fields a history needs.

## Options

### Option A: Accept the attempt history, and add `--reason` to `complete` and `fail`

`aic task complete <id> [--reason "<text>"]` and `aic task fail <id> [--reason "<text>"]` pass the reason to the attempt record they already close. `aic task history` already prints a reason when there is one. There is no new file and no schema change.

This answers "why did it fail" and "why was it completed". It leaves the ready times and the goal's earlier statuses unanswered.

### Option B: A separate append-only transition log

A new file, `transitions.json`, beside the task file, in the same versioned shape as `executions.json`. One record per task status change: `id`, `entity` (`task` or `goal`), `entity_id`, `from_status` (null at creation), `to_status`, `at`, `source` (`cli` or `coordinator`) and `reason`. It is written under the state lock.

It answers every question in the table above. It costs:

- a model, a registry and validation rules (the last record must match the entity's status; each `from_status` must match the record before it);
- wiring in `transition_task_status`, `ExecutionStarter`, `ExecutionOutcomeRecorder` and goal reconciliation;
- a rule for the write order, and a detectable crash shape, because two files cannot be written together;
- overlap with the attempt records, which already record starts and ends, so the same event would be written twice and checked for agreement;
- parity tests between the CLI and the library, as the attempt records needed.

It is a feature of a similar kind and size to the execution records.

### Option C: Keep the history on the task itself

Add a `history` list to each task in `tasks.json`. This needs schema version 2 and a migration that old code cannot read. It also makes every task rewrite longer. Rejected for the same reasons as the equivalent option in the execution records note.

### Option D: Fold status changes into the execution records

Extend `executions.json` into an event log for every status change. This mixes "a run" and "a status change" in one record type, and it complicates the rule that an attempt number is derived from the order of a task's records. The execution records note considered and rejected an event log.

### Option E: Do nothing, not even `--reason`

The attempt history stays as it is. A failed task keeps an empty reason.

## Recommendation: Option A

1. **The history that matters for control is already kept.** Every start and every end of a run has a time, a route and an outcome, and a requeue has a reason. Those are the facts a person needs to recover or to explain a run.
2. **The missing facts are low-value or derivable.** The time a task became ready says little about a run. A goal's earlier statuses follow from its tasks' history.
3. **The strongest unmet need is the reason for a failure.** Option A answers it in a few small commits with no new file and no schema change, and it was already approved in principle.
4. **A transition log should be designed once, with Phase 3.** Approval, identity and permissions will decide what it must record. Building B now means redesigning it then.
5. **B would be a feature of similar size to the execution records work.** Spending that before there is a question it must answer is the wrong order.

What Option A leaves open, stated plainly: G4's second half stays partly open. There is still no record of when a task became ready, and no history of a goal's statuses. This note should be reopened if any of these happens:

- Phase 3 adds approvals, permissions or an identity for the person acting.
- Someone needs to answer "when and why did this become ready" and cannot.
- An audit requirement appears.

## Tests for Option A

- `aic task complete <id> --reason "<text>"` closes the attempt as `completed` with that reason, and `aic task history` shows it.
- `aic task fail <id> --reason "<text>"` does the same for `failed`.
- Without `--reason`, both behave as they do now, and the record's reason is empty.
- A blank `--reason` is refused with exit status 1, and nothing changes.
- A refused command, such as `complete` on a task that is not running, writes nothing, as before.
- The CLI and the library keep recording attempts alike, so the parity test covers a reason.
- `aic task complete --help` and `aic task fail --help` show the option.

The write order does not change. The task moves first, then the record is closed, as INV-16 requires.

## Risks

- **Reasons are free text.** They can hold sensitive details, as the security policy already says for adapter messages. This does not change.
- **An optional reason is easy to skip.** Making it required on `fail` would force one, at the cost of breaking existing use. See question 2.
- **The ready times stay unrecorded.** This is accepted under Option A and is the reason to revisit.
- **Option A could be mistaken for closing G4.** The status documents will keep G4 listed, with its remaining part described.

## Open questions for the maintainer

1. Accept Option A and defer a transition log to the Phase 3 design? Recommendation: yes.
2. Should `--reason` be optional on `fail`, or required as it is on `requeue`? Recommendation: optional. `requeue` is a recovery action taken on a guess that a process is dead. `fail` is a plain outcome, and requiring a reason would break existing use.
3. Should `aic task ready` accept a reason too? Recommendation: no. There is no record to attach it to.
4. If you want Option B anyway: should it cover tasks only, or goals too? Recommendation: tasks only, since goal status is derived. It should write the log after the state change, so a missing last record is the one detectable crash shape.

## After this decision

If Option A is accepted, the build is small: `--reason` for `complete` and `fail` and its tests, then the documents. If another option is chosen, this note is revised and approved again before any code.
