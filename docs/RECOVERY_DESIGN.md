# Design Note: Recovering a Task Left in `running`

**Status: Accepted and implemented (Option A).** `aic task requeue` was built as described under Recommendation. Option B, automatic detection, is not built. It addresses gap G5 in [STATUS.md](STATUS.md).

## Problem

A task enters `running` when it is started. It leaves `running` only when an outcome is recorded. If the process dies in between (a crash, a closed terminal, a lost machine), nothing records an outcome and the task stays `running`.

This was reproduced with the real CLI. After a task was started and its process abandoned:

- The task stayed `running`, the goal stayed `in_progress`, and `aic validate` passed. Nothing signals that anything is wrong.
- `aic task ready` was refused with `Invalid task status transition: running -> ready`, and `aic task start` was refused because the task status is `running`. The task cannot be retried.
- `aic task complete` was accepted. A person can record a success that never happened.
- `aic task fail` was accepted, and it fails the whole goal. Afterwards the goal was `failed`, its untouched sibling task could not be marked ready (`parent goal is failed`), and the original task could never run again.

So the only ways to get unstuck are to claim a false success or to fail the goal permanently. Neither is a recovery.

## Facts about the current code

- A task stores `id`, `goal_id`, `title`, `description`, `status`, `created_at`, and `updated_at`. There is no start time, owner, or attempt count. `updated_at` is the time of the last status change, so it is the only hint of how long a task has been `running`.
- When this note was written, the transition table allowed `running` to go only to `completed` or `failed`. Both are terminal. The table now also allows `running → ready`; see "Found while implementing".
- A goal's status is derived from its tasks. Any `failed` task makes the goal `failed`, and a failed goal accepts no new work.
- Readiness, and so admission, refuses a task unless it is `ready` and its goal is open. `aic task start` and the library `ExecutionStarter` both enforce this (INV-4).
- The outcome recorder accepts an outcome only for a `running` task (INV-2).
- No component knows whether a process is still alive, and there is no execution history to consult.

## Requirements

1. A person can unblock a dead `running` task without failing the goal.
2. Retrying must not bypass readiness. A requeued task must pass readiness before it runs again (INV-4).
3. The action is explicit and deliberate, never automatic or silent.
4. Prefer no change to the shape of the persisted state files, so no schema version bump.
5. Do not pretend to detect a dead process. The tool cannot tell a dead process from a slow one.

## Options

**A. Operator requeue (recommended).** Add the transition `running -> ready` and a command, `aic task requeue <task-id> --reason "<text>"`. A person decides that the earlier run is dead and puts the task back in the queue.

- Pro: the smallest change that removes the dead end. No new status and no new stored field, and goal status is unaffected, because `running` and `ready` both leave a goal `in_progress`.
- Pro: the task goes back through the normal gates, so INV-4 still holds.
- Con: it relies on the person being right. If the process is in fact still alive, the task could run twice.
- Con: the reason is printed but not stored until execution records exist.

**B. An `interrupted` status with automatic detection.** Add a status, record a start time and an owner or lease, and mark a task `interrupted` when its heartbeat or deadline lapses.

- Pro: no human judgement is needed to notice a dead task.
- Con: much larger. It needs a start time and heartbeat on the task, a process model, a place for the detector to run, a new status in the lifecycle, goal derivation, validation, and readiness, and a decision about what a detector may do on its own. It also depends on execution records and on a real adapter that can report liveness, and neither exists.
- This is the right long-term direction. It should be built on top of A, not instead of it.

**C. Allow `failed -> ready`.** Let a failed task be retried.

- Con: it breaks the rule that `completed` and `failed` are terminal (INV-3), and a goal's status would flip back after having been `failed`. Rejected.

**D. Do nothing and document the workaround.**

- Con: the only workarounds are the false success and the permanent goal failure shown above. Rejected.

## Recommendation: Option A

Behaviour:

- `aic task requeue <task-id> --reason "<text>"` moves a task from `running` to `ready` and prints the task, its previous `Updated` time, and the reason.
- `--reason` is required and must not be blank.
- It refuses any task that is not `running`, with the same style of message as the other lifecycle commands.
- It refuses a task whose goal is `completed` or `failed`, because such a task could not be started again anyway (see question 2).
- It never changes a goal to `failed` or `completed`. The goal is reconciled as usual and stays `in_progress`.
- It does not start the task. Starting still goes through `aic task start` and readiness.

What changes in the code: one entry in the transition table, one new command, and tests. What does not change: the statuses, the persisted shape, the schema version, goal derivation, readiness, and admission.

Tests the note planned:

- Requeue from `running` works and the task is then `ready`.
- Every other status is refused.
- A blank or missing reason is refused.
- A closed goal is refused.
- The goal stays `in_progress`.
- The requeued task passes readiness and can be started.
- Completed and failed tasks still cannot transition (INV-3).
- A failed save leaves the previous file intact (INV-9).

Two invariants were added to [STATUS.md](STATUS.md): INV-14 (only a `running` task can be requeued, and requeueing never changes a goal to a closed status) and INV-15 (`aic task ready` never requeues; only `aic task requeue`, with a reason, does).

## Risks

- **Double execution.** If the earlier process is still running, requeueing and starting again runs the task twice. The command cannot prevent this. It makes the action deliberate (a required reason and a printed `Updated` time) and the documentation says so plainly. Real protection needs Option B.
- **No audit trail yet.** Until execution records exist, the reason and the fact that a requeue happened are not stored.
- **False success is still possible.** `aic task complete` on a dead task is still accepted. Requiring evidence for completion is separate work.

## Open questions for the maintainer

1. Should the reason be stored now? That needs a new field on the task, a schema version bump to 2, and a migration. Recommendation: no. Wait for execution records, which are the natural place to store it.
2. Should requeue be refused when the goal is closed? Recommendation: yes, as described above.
3. Should there be a confirmation prompt? Recommendation: no. The tool is non-interactive, and a required reason is the deliberate step.

Answered: the maintainer approved the recommendation on all three. The reason is not stored yet, a task in a closed goal is refused, and there is no confirmation prompt.

## Found while implementing

`aic task ready` has no status check of its own. It checks the parent goal and then asks the registry for the transition to `ready`, and the registry accepts any edge in the transition table. So adding `running → ready` to the table by itself would have turned `aic task ready` into a silent requeue: no reason, exit status 0. It was reproduced with the table change applied and no guard. The existing tests did not catch it, because none of them asks `aic task ready` to handle a `running` task.

The change was therefore built guard first. `aic task ready` was made to refuse a `running` task before the table gained the new edge, so the CLI never had a state where `aic task ready` could requeue. Afterwards the table allows the edge, and the CLI reaches it only through `aic task requeue`. The library call `TaskRegistry.update_task_status` allows the edge as well; no library code uses it for this.

The failed-save case from the planned tests is not repeated for this transition. The existing test for a failed status update covers the save path that every transition shares.

## After this decision

Execution records come next: a new versioned state file with one record per attempt, including the start time, the outcome, and, for a requeue, the reason. They give Option B the start time it needs, and a later detector, lease, or timeout would build on them.
