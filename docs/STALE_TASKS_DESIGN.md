# Design Note: Seeing How Long a Task Has Been `running`

**Status: Proposed.** Nothing described here is built. It addresses what is still open in gap G5 in [STATUS.md](STATUS.md): nothing helps a person decide that a `running` task is dead. It needs the maintainer's decisions before any code is written.

## Problem

`aic task requeue` lets a person put a dead `running` task back in the queue ([RECOVERY_DESIGN.md](RECOVERY_DESIGN.md)). It cannot tell whether the task is really dead. If the process is still alive, requeueing runs the task twice. The person has to decide, and today they have very little to decide with.

This was reproduced with the real CLI, with a temporary data directory, on Linux.

- To find the stuck task, a person runs `aic task list`. It prints every task with its status and its creation time. It has no filter and no start time. In the reproduction every entry showed `Status: running` and `Created:`, and nothing about when the task started.
- To learn when a task started, a person runs `aic task history <task-id>` or `aic task status <task-id>` one task at a time.
- A live run and a dead run look the same on disk. A coordinator run was left sleeping in its adapter and read from another process: the attempt was `Route: coordinator (slow)`, `Ended: still open`. While it ran, another command took the state lock and started a different task, as INV-22 says it can. The run was then killed with `kill -9`, and its attempt record was compared with the record read while it was alive. They were identical. The record holds no process ID, no host and no heartbeat.
- So the files can say how long a task has been `running`. They cannot say whether anything is still running it.

A listing of how long tasks have been `running` therefore helps a person to decide, and it does not detect anything. It does not close G5. The risk that G5 names, a live run requeued and run twice, stays.

## Facts about the current code

- Every start from the CLI or the coordinator opens an attempt record before the task moves to `running` (INV-16). An open record always has a start time: the model refuses an open record without one.
- A task's `updated_at` is written in one place, `TaskRegistry.update_task_status`. While a task is `running` it holds the time the task moved to `running`. Reproduced: the attempt's `started_at` and the task's `updated_at` were under a millisecond apart, for a CLI start (`03:48:40.650941` and `03:48:40.651677`) and for a coordinator run (`03:48:40.730407` and `03:48:40.731236`).
- A task that was already `running` before execution records existed has no attempt record. `aic task history` prints `No attempts recorded.` and `aic validate` accepts it, by design. Reproduced by removing the record of a running task.
- Both times are UTC ISO-8601 strings with a `+00:00` offset, and `datetime.fromisoformat` reads them. Neither model checks the format. An `ExecutionRecord` accepted `started_at="garbage"`. A date with no offset reads without a time zone.
- `aic task requeue` refuses a task that is not `running` (`only a running task can be requeued (task status is ready)`), so an out-of-date listing cannot cause a finished task to be requeued.
- The process adapter's time limit is 60 seconds by default and is set per target in code. It is not stored in the attempt. A CLI attempt has no limit at all: a person may take any time between `aic task start` and `aic task complete`.
- The read-only listings take no lock. Each state file is replaced atomically, so a reader never sees a half-written file. Two files read one after the other can disagree if a writer runs in between.
- Nothing uses the recorded start time. G5 says so, and the recovery note left detection as its Option B, which needs an owner or lease, a heartbeat, and an adapter that can report liveness.

## Requirements

1. It is read-only. It never writes, requeues, fails or completes a task.
2. It is advisory. It reports how long, and never says that a task is dead.
3. It does not present a guessed time limit as a fact. The project already carries guessed limits (G13).
4. It covers tasks that started before records existed, with a time that is labelled as an estimate.
5. It survives bad data. A time that cannot be read, or that is in the future, neither crashes it nor hides a task.
6. It adds no stored field and needs no schema change.
7. It fits the lock model: a new command is classified, and a read-only one is listed as read-only.

## Options

### Decision 1: what to build

**1A. A new read-only command that lists the `running` tasks and how long each has been running (recommended).** It sorts the oldest first and offers an optional `--older-than` filter.

- Pro: it answers the question a person has. It is small, adds no stored data, and leaves `aic task list` as it is.
- Con: one more command, and it needs a place in the classification test.

**1B. Add a `running` filter and a "running for" line to `aic task list`.**

- Pro: no new command.
- Con: it changes the output of an existing command that people and scripts may already read, and `list` would then do two jobs.

**1C. Make `aic validate` report tasks that have run for a long time.**

- Con: validation reports state that is wrong. A long run is not wrong, and a person doing manual work between `start` and `complete` is normal. A report that fails a validation for it would teach people to ignore validation. Rejected.

**1D. Record an owner in the attempt (process ID, host, a heartbeat) so that the listing can check whether it is alive.**

- Pro: it is the only option that can detect a dead run.
- Con: it is a new field in `executions.json`, so a schema version bump and a migration. A process ID can be reused and means nothing on another host. A heartbeat needs a writer during the adapter, which breaks the rule that nothing holds or takes the lock while an adapter runs (INV-22), or needs a second file. It also needs a real adapter that can report liveness, and none exists. This is the recovery note's Option B. It should be built on top of 1A, not instead of it, and it is not part of this note.

**1E. Do nothing.**

- Con: the person keeps deciding with no evidence. Rejected, because 1A costs little.

### Decision 2: since when

**2A. The open attempt's start time, and for a running task with no open attempt, the task's `updated_at`, labelled as an estimate (recommended).**

- Pro: the two agree to within a millisecond for tasks started with records, so the fallback is accurate. It is the only source for a task that started before records existed.
- Con: a person who edits `tasks.json` by hand changes `updated_at`, and the estimate is then wrong. The label says it is an estimate.

**2B. Open attempts only.** A task that started before records existed would not be listed at all, and it is exactly the kind of task that is likely to be old. Rejected.

**2C. `updated_at` only.** It ignores the attempt record that already holds the exact time and the route. Rejected.

### Decision 3: what counts as long

**3A. No default. List every `running` task with its time, and accept an optional `--older-than <number><s|m|h|d>` filter (recommended).**

- Pro: no guess. The person says what long means for their work. `--older-than 30m`, `2h` and `1d` are easy to type and to read.
- Con: the plain command lists tasks that are not stale.

**3B. A default threshold, for example one hour.** Any number is a guess. A manual task can legitimately run for days, and a process adapter is limited to a minute. Rejected.

**3C. A required threshold.** It forces a number on every use. Rejected.

**3D. Per-target limits stored in the attempt.** It needs a new field and only covers the coordinator route. It belongs with 1D. Not now.

### Decision 4: the name

**4A. `aic task running` (recommended).** It says what it lists and makes no claim.

**4B. `aic task stale`.** It claims a judgement that the files cannot support.

**4C. `aic task stuck`.** The same objection, stronger.

### Decision 5: times that cannot be used

**5A. Show the task, and say what is wrong (recommended).** A start time in the future (the clock moved back, or the file was edited) is shown as `Running for: 0s (the start time is in the future)` and is not matched by `--older-than`. A time that cannot be read is shown as `Running for: unknown (the start time cannot be read)` and is kept by `--older-than`, because a task must never disappear from the list because its data is bad.

**5B. Skip such tasks or stop with an error.** A damaged record would then hide the very task the person is looking for. Rejected.

### Decision 6: the lock

**6A. Read-only, no lock, like `aic task history` (recommended).**

- Pro: consistent with the other listings, and it runs while another command holds the lock.
- Con: it reads `tasks.json` and then `executions.json`. A task that finishes between the two reads is listed with its older estimate, so it can look old for a moment. `aic task requeue` refuses a task that is not `running`, so this cannot cause a wrong requeue.

**6B. Take the lock, as `aic validate` does.** It gives a consistent view and costs a wait of up to the lock timeout. The listing is advisory, so this is not worth it.

### Decision 7: the exit status

**7A. Always 0 (recommended).** The command is advisory and it is not a health check.

**7B. Exit 1 when it finds a task.** It would turn a long manual task into a failing command in a script. Rejected.

## Recommendation

Build 1A with 2A, 3A, the name 4A, 5A, 6A and 7A. The output would look like this:

    Running tasks: 2

    - 9d12e597-3305-45c5-8f3e-5c476fe2c744
      Title: task two
      Goal: 201c0396-8aae-4607-adbc-68253067ddeb
      Route: coordinator (process)
      Since: 2026-10-19T03:48:40+00:00
      Running for: 3h 12m

    - 3b2981db-25c8-415f-8527-53cab52b908c
      Title: task four
      Goal: 5f0c4c5e-0a0b-4a53-9a58-1d6c1b0f6a11
      Route: unknown (before records existed)
      Since: 2026-10-16T21:02:11+00:00 (estimated from the last update)
      Running for: 2d 6h

    A task listed here may still be running. Requeueing a live run runs the task twice.
    To put a task back in the queue: aic task requeue <task-id> --reason "<text>"

With `--older-than 1d` only the second task is listed. With nothing to show it prints `No running tasks.` or `No running tasks older than 1d.` The IDs and times above are examples in the intended format, not output.

The time that is shown for a task is the start of the latest open attempt. A task with two closed attempts and one open one is timed from the open one. Closed attempts are ignored.

## What this does not do

- It does not detect a dead run, and G5 stays open for detection. Only a recorded owner or lease (1D) can do that.
- It does not stop a person from requeueing a live run. It prints the risk next to the command.
- It does not change `aic task complete`, which still accepts a false success on a dead task.

## Tests the build needs

- Only `running` tasks are listed, oldest first, and a task in any other status is not.
- The time comes from the latest open attempt. A task with closed attempts and one open one is timed from the open one. A task with no open attempt uses `updated_at` and is labelled as an estimate.
- The route shows `cli` or `coordinator (target)`, and `unknown` for a task with no attempt.
- `--older-than` filters, including exactly at the limit. `30s`, `15m`, `2h` and `1d` are read. `0m`, `-5m`, `5`, `5w`, `m` and a decimal are refused with a message and a non-zero status, and nothing is printed first.
- A start time in the future is shown as such and is not matched by `--older-than`. A start time that cannot be read is shown as unknown and is kept by `--older-than`.
- The command never writes: both state files are byte-identical afterwards. It runs while another process holds the lock.
- The classification test lists it as read-only. The elapsed time is computed from a clock that the test supplies, so no test depends on the real time.
- An open attempt for a task that is not `running`, the G11 case, is not listed.

## Risks

- **Age is not death.** A long manual task is normal. The command never says dead or stale, and the output says that a listed task may still be running.
- **A wrong requeue is still possible.** The command cannot prevent it. Real protection needs 1D.
- **A wrong clock.** The elapsed time uses the clock of the machine that runs the command. If the start time was written by a machine with a different clock, the time is off by the difference. The project is local-first, so this is normally one machine.
- **Output as an interface.** The text is for a person. It is not a stable format for scripts, and the exit status carries no meaning.
- **Estimated times.** A task with no attempt record is timed from `updated_at`, which a hand edit of `tasks.json` can change. The output says that it is an estimate.

## Open questions for the maintainer

1. Name the command `aic task running` (4A) rather than `stale` or `stuck`? Recommendation: yes. It makes no claim that the files cannot support.
2. List every running task with no default threshold, and filter with an optional `--older-than` (3A)? Recommendation: yes. A default would be a guess.
3. Fall back to the task's `updated_at` for a running task with no open attempt, and label it as an estimate (2A)? Recommendation: yes. Those tasks are the ones most likely to be old.
4. Leave `aic task status` and `aic task list` as they are (1A, not 1B)? Recommendation: yes.
5. Leave detection (1D) for the first real adapter, which can report liveness? Recommendation: yes. Detection needs an owner and a heartbeat, and a real adapter to give them meaning.

## After this decision

If the recommendation is accepted, the build is small: a function that turns the two registries and a clock into rows, a parser for the duration, the command with its classification, and the documentation. It can be done in three stages: the library and its tests, the command and its tests, then the documentation and the Windows record. A recorded owner or lease (1D) is the long-term way to close the rest of G5, and the listing would then show whether the owner is alive.
