# Design Note: Coordinator CLI

**Status: Proposed; stages 1 and 2 are built.** Stage 1 (Decision 2A, tying each outcome to its attempt) and stage 2 (the state guard of Decision 1B) are built, and what happened is at the end of this note. The CLI, the `noop` adapter and the rest are not implemented, and the decisions behind them need the maintainer's acceptance before any code is written. It addresses G6 in [STATUS.md](STATUS.md) (the coordinator cannot be reached from the CLI) and G12 (found while preparing this note). It is the first design note of Phase 3 in [ROADMAP.md](../ROADMAP.md) and covers the path from a CLI command to an adapter and back. Permissions, limits, timeouts and the detection of dead runs get only their hook points here. Each needs its own note.

## Problem

`ExecutionCoordinator` runs the whole path: it resolves the adapter for a target, starts the task, calls the adapter and records the outcome. No CLI command calls it, and no adapter exists (G6). Phase 3 would add both.

Before designing that, the real coordinator was run with a slow fake adapter, on the current code (Linux sandbox), while a person used the CLI on the same data directory. Three things came out of it.

**Superseded runs.** The adapter took 4 seconds. While it ran, the task was `running`. A person ran `aic task requeue` and then `aic task start` on the same task. When the adapter finished, the recorder accepted its result because the task was `running` again. It closed the open attempt, which was the person's second attempt (route `cli`), as `completed` with the adapter's reason, and the coordinator reported `completed`. In a second run, with the requeue only and no second start, the recorder refused the outcome with `task status is ready`, and the adapter's result was dropped.

**No lock in the library.** The state lock is taken by `main`, not by the library. Eight coordinators were started at once on eight different tasks, each with an instant adapter. In three runs, 3, 4 and 4 coordinators reported `completed`, but exactly one task ended `completed` each time. Five to seven tasks stayed `ready`, and in one run two were left `running`. `aic validate` reported open records whose task was `ready`.

**A whole-command lock would block recovery.** On Windows, a writing command that could not get the lock stopped after about 10 seconds and wrote nothing (STATUS, file locking). A coordinator command that held the lock for its whole run would do that to every other writing command for as long as the adapter ran. That includes `aic task requeue`, which is the only way to recover a dead run.

## Facts about the current code

- `coordinate` resolves the adapter, calls `ExecutionStarter.start` (admission, open the attempt record, move the task to `running`), calls `adapter.execute`, and calls `ExecutionOutcomeRecorder.record` (check that the task is `running`, move it, close the attempt, reconcile the goal).
- `ExecutionAdapter` is a protocol with one method, `execute(request) -> ExecutionOutcome`. `ExecutionAdapterRegistry` maps target names to adapters. Nothing registers an adapter outside tests.
- The recorder checks only that the task is `running`, and `close_attempt` closes whichever attempt is open for the task. The start result does not carry the attempt's ID, so an outcome cannot say which attempt it belongs to. (Stage 1 changed this; see the end of this note.)
- The adapter call is synchronous and in the same process. It has no timeout and no cancellation. An exception, an invalid result or a result for another task becomes a `failed` outcome (INV-6).
- `main` holds the state lock for every command that is not read-only (INV-20). A new command would hold it for the whole adapter run unless it is classified differently.
- Every attempt records `started_at`. Nothing reads it.
- The project has built no shell, browser, model or Git adapter, by design.

## Requirements

1. The lock is never held while an adapter runs, as the file locking note already requires.
2. An outcome applies only to the attempt it belongs to. A superseded run must not change a newer attempt.
3. Recovery stays possible while an adapter runs: `aic task requeue` must work.
4. A crash leaves a detectable shape, as INV-16 does. A process killed during an adapter leaves an open attempt and a `running` task, which `requeue` already recovers.
5. A rejected request or refused command writes nothing (INV-1, INV-18).
6. Nothing is loaded or run that the code did not register itself.
7. Standard library only, on Windows and Linux.

## Decisions

### Decision 1: Where the lock is held

**Option 1A: hold it for the whole command.** The simplest, because `main` already does it. It blocks every other writing command for the length of the adapter and makes `requeue` impossible during a run. Rejected.

**Option 1B: hold it around the state operations only.** The coordinator takes the lock for the start (admission and moving the task to `running`) and again for recording the outcome. The adapter runs between them, with the lock free. The coordinator gets an optional `state_guard`, a function that returns a context manager. It defaults to doing nothing, so library use and existing tests do not change. The CLI passes one that takes `state_lock`. The command cannot also sit under `main`'s whole-command lock, so the CLI gets a third class of command: read-only, locking, and self-locking.

**Option 1C: keep adapters out of the CLI.** A separate worker starts a task with `aic task start`, does the work elsewhere and reports with `aic task complete --reason` or `aic task fail --reason`. That is the operator path that exists today. It needs nothing new, and it also gives no coordinator CLI.

**Recommendation: 1B.** It is the only option that gives a coordinator CLI without blocking recovery. 1C stays available and is not removed.

### Decision 2: Tying an outcome to its attempt

**Option 2A: carry the attempt ID.** The start result returns the ID of the attempt it opened. The coordinator passes it to the outcome. The recorder, given an ID, refuses the outcome unless that attempt is still the task's open attempt. A refused outcome changes nothing. The coordinator returns `rejected`, and its reason includes what the adapter reported, so the result is not silently lost. An outcome without an ID behaves as it does now, so the operator path and existing callers are unaffected.

**Option 2B: match by start time.** Compare `started_at`. Fragile, and two attempts can share a timestamp. Rejected.

**Option 2C: do nothing.** Leaves the defect above in place. Rejected.

**Recommendation: 2A.**

### Decision 3: The command, and where adapters come from

**Option 3A: `aic task run <task-id> --target <name>`, and a read-only `aic task targets`.** `run` goes through admission, start, the adapter and the outcome. It prints the task, the target, a result (`completed`, `failed` or `rejected`) and a reason, and exits 0 only for `completed`. Adapters are registered in code, in one place. `targets` lists them.

**Option 3B: load adapters by name from configuration.** This would let a settings file name code to import and run. Rejected: it makes configuration a way to run arbitrary code.

**Option 3C: no CLI command, library only.** G6 stays open. Phase 3 has nothing to build on.

**Recommendation: 3A.**

### Decision 4: The first adapter

**Option 4A: a `noop` adapter.** It completes at once with the reason "noop adapter: no work was done". It proves the whole path end to end and is harmless. The CLI tests inject slow and failing adapters through a registry parameter, so no test adapter ships. It can record a task as `completed` when no work happened, which is the same kind of false-success risk the recovery note describes for `aic task complete` on a dead task. The reason text, and `aic task targets` saying what it does, are how that is made visible.

**Option 4B: ship none.** `aic task run` would always report an unknown target. Honest and useless.

**Option 4C: an allowlisted local command adapter.** Needs a permissions model and out-of-process execution first. Rejected for now.

**Recommendation: 4A.**

### Decision 5: Hook points

- **Permissions.** `ExecutionAdmission.evaluate` is already the one place that decides whether a request may start. A permission check belongs there, before an attempt opens, so a refusal writes nothing. What a permission is, and who grants it, needs its own note.
- **Timeouts and limits.** An adapter runs in the same process and Python cannot safely stop a running call from outside. A timeout in this model could only notice lateness. Real timeouts and limits need adapters that run in a child process that can be killed. That is a prerequisite for any adapter with side effects, and the `noop` adapter does not need it. It gets its own note.
- **Dead runs.** `started_at` is recorded for every attempt. A read-only listing of `running` tasks whose open attempt began more than a given time ago would use it. It would be advisory and change nothing. Nothing should requeue automatically: a live process would then run twice (see the recovery note). Automatic action needs heartbeats or leases.

## Recommended order

1. **Attempt identity** (Decision 2A), library only. No new command.
2. **The state guard** (Decision 1B), library only.
3. **The CLI** (Decisions 1B, 3A and 4A): `aic task run`, `aic task targets`, the `noop` adapter and the third command class.
4. **Documentation**, including INV-20 amended to cover self-locking commands, and G6 and G12 closed.

Tests for each stage:

- Stage 1: the superseded run above fails the way it should: an outcome for a superseded attempt is refused and the newer attempt is untouched. Both the requeue-and-restart case and the requeue-only case. An outcome without an ID still works.
- Stage 2: during `adapter.execute` the lock is free (the adapter takes it itself). A refused or rejected request writes nothing.
- Stage 3: eight `aic task run` processes on eight tasks all end `completed`, with eight closed records. A held lock stops `run` cleanly with nothing changed. `aic task requeue` works while a slow adapter runs. The classification test covers three classes. `aic validate` passes after each case.

## Risks

- **A self-locking command can forget to lock.** The three-way classification test, and a test that holds the lock from another process, guard against it.
- **The lock is free during the adapter.** A person can complete, fail or requeue the task while it runs. The outcome is then refused and the adapter's work is done but not recorded. The result is printed in the reason. This is the price of not blocking recovery.
- **Attempt identity does not stop a live run from executing twice** after a person requeues a live process (G5). It stops the stale run from changing the new attempt.
- **The adapter runs inside the CLI process.** A bug in an adapter can crash the command. INV-6 covers exceptions, not a hang or a hard crash. A killed process leaves an open attempt and a `running` task, which `requeue` recovers.
- **`noop` can mark a task `completed` with no work done.** See Decision 4.

## Open questions for the maintainer

1. Hold the lock around the state operations only, never the adapter (Option 1B)? Recommendation: yes.
2. Tie each outcome to its attempt first (Option 2A), as a library fix before any command? Recommendation: yes. It fixes a defect that exists today.
3. Name the command `aic task run <task-id> --target <name>`, with `aic task targets`? Recommendation: yes. The alternative is a top-level `aic run`.
4. Ship the `noop` adapter as the first one (Option 4A)? Recommendation: yes. The alternative is to stop after stages 1 and 2 and ship no command yet.
5. Give permissions, timeouts and limits their own notes, and require out-of-process adapters before any adapter with side effects? Recommendation: yes.
6. Add a read-only listing of stale `running` tasks after that, with no automatic recovery? Recommendation: yes.

## Stage 1: built

Everything in this section was observed on Linux.

- `ExecutionStartResult` gained an optional `attempt_id`, set from the record that `open_attempt` returns. A request that is not admitted names none.
- `ExecutionOutcome` gained an optional `attempt_id`, and a blank one is refused. `ExecutionOutcomeRecorder.record` checks it after the task-status check and before anything is written. If the task's open attempt is not that attempt, or there is none, the outcome is refused as `attempt was superseded; the adapter reported <outcome>: <reason>` and nothing changes (INV-21).
- The coordinator passes the attempt it started with every outcome it records: the adapter's own, and the failed outcomes it builds for an exception, an invalid result and a result for another task.
- An outcome with no `attempt_id` behaves as before, so the CLI's operator path is unaffected. All 413 earlier tests passed unchanged.
- The original scenario was run again with the real CLI. The adapter's late result was reported as `rejected | attempt was superseded; the adapter reported completed: adapter finished`. The person's second attempt stayed open, the task stayed `running`, and `aic validate` passed. The requeue-only case still reports `task status is ready`, and a run with no interference still completes and closes its own attempt.
- The suite grew from 413 to 425 tests. Ten changes made one at a time were each caught by a test: the start result dropping the ID, the recorder ignoring it, the recorder checking only that some attempt is open, a refused outcome reporting `completed`, the refusal hiding what the adapter reported, a blank ID allowed, and the coordinator leaving the ID out of each of its four paths.
- A superseded run's work is still not recorded. The result is returned to the caller in the refusal reason, which is the cost of not blocking recovery.

## Stage 2: built

Everything in this section was observed on Linux.

- `ExecutionCoordinator` takes an optional `state_guard`, a function that returns a context manager. It defaults to a context that does nothing, so existing callers and all 425 earlier tests are unchanged.
- The coordinator enters the guard around the start and, through one helper, around each of the four outcome recordings: the adapter's own, and the failed outcomes it builds for an exception, an invalid result and a result for another task. A journal test shows the order: enter, exit, adapter, enter, exit. A refused start enters once, and an unknown target never enters.
- With the real state lock as the guard, an adapter can take the lock itself while it runs, so the coordinator does not hold it then.
- The earlier experiment was run again with the guard, three times: eight coordinators on eight tasks all reported `completed`, all eight tasks ended `completed`, all eight records were closed, and `aic validate` passed. Before, 3, 4 and 4 reported `completed` and exactly one task was. The new subprocess test failed on each of five runs with the guard ignored.
- Recovery stays possible. While a six-second adapter ran under the guard, `aic project add` and `aic task requeue` each finished in under a tenth of a second. The adapter's late outcome was then refused with `task status is ready`.
- The suite grew from 425 to 433 tests. Eight changes made one at a time were each caught by a test: the start unguarded, all outcome recordings unguarded, each of the four recording paths bypassing the guard on its own, the adapter run while the guard is held, and the guard argument ignored.
- Nothing passes a guard yet, because nothing in the CLI reaches the coordinator. A coordinator built without one still takes no lock.

## After this decision

Stage 3, the CLI, is next: `aic task run`, `aic task targets`, the `noop` adapter and the third command class (Decisions 1B, 3A and 4A), with the classification test and INV-20 updated. If a different option is chosen anywhere above, this note is revised and approved again before any further code.
