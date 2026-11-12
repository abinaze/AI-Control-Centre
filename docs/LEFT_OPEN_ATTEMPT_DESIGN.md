# Design Note: Closing an Attempt That Was Left Open

**Status: Accepted as recommended, and built.** This note decides what to do about G11 in [STATUS.md](STATUS.md): an attempt that stays open for a task that is `completed` or `failed`, which nothing can close from the CLI. It follows [EXECUTION_RECORDS_DESIGN.md](EXECUTION_RECORDS_DESIGN.md), which found the problem and did not build a repair command. The evidence was observed on Linux with the real CLI, with the failing write simulated. Nothing in the evidence was run on Windows. What was built, and what was run on Windows afterwards, is in the record at the end of this note.

## Problem

When `aic task complete`, `aic task fail` or the coordinator ends a run, the task moves first and its attempt record is closed after it. This order is on purpose, because a crash between the two steps leaves an open record for a task that is no longer running, which `aic validate` can see. But when the records file cannot be written at that moment, the command reports an error after the task has moved, and the task is final. Nothing starts a final task again, so nothing closes its attempt.

The state is not harmless, and the observations below show three ways in which it is not. The person who meets it has only one way out, which is to edit `executions.json` by hand, and the edit that the notes suggest writes the wrong outcome.

## Evidence

All of this was run on Linux, with the real CLI and a temporary data directory. The write that fails was simulated: a launcher made `ExecutionRecordRegistry.close_attempt` raise `StateFileError`, which is the error that an unreadable or unwritable file gives. G11 was first reproduced with a corrupted `executions.json`, and that was not repeated here. The rest of the code and the commands were the real ones.

1. **The CLI path.** A task that was started with `aic task start` was ended with `aic task complete --reason done`. The command printed `Task status updated.`, `ID:` and `Status: completed`, then `Error: executions.json cannot be written: simulated`, and exited with status 1. The task was `completed`. Then:
   - `aic validate` failed, with `Execution record <id> is open but task <id> is completed`.
   - `aic task history` showed `Ended: still open` and the note that the task is not running, so the attempt was left open.
   - `aic task requeue` refused, with `only a running task can be requeued (task status is completed)`, and `aic task start` refused, because the parent goal was completed.
   - `aic goal archive` refused, with `goal <id> cannot be archived: execution record <id> is still open` and `Nothing was changed.` So the goal cannot be archived, and by the rule of `aic project remove`, which refuses while a goal names the project, the project cannot be removed while that goal is registered. The removal itself was not tried.
   - The reason `done` was stored nowhere, because the command prints and stores it after the close.
2. **The hand edit.** The edit that STATUS describes, a time in `ended_at` and `abandoned` in `ended_as`, made `aic validate` pass, and `aic goal archive` then succeeded. The record says `abandoned` for a task that completed.
3. **The coordinator path.** `aic task run --target noop` was run with the same failing close. It printed the error. The task was `completed`, and the goal was `in_progress` in `goals.json`. `aic validate` reported two problems: `Goal <id> status mismatch: persisted=in_progress, derived=completed` and the open record. `aic goal status <goal>` then set the goal to `completed`, and `aic validate` reported only the open record.

When this note was written, these were not observed: a real unwritable file, on any platform, and a real crash between the two steps, and nothing in this note had been run on Windows. A real unwritable file was observed on Windows later, as the record at the end of this note says.

## Facts about the code

- `_finish_task` calls `transition_task_status`, which moves the task and reconciles the goal in one call, and then closes the attempt. A failed close therefore leaves the goal right and the attempt open.
- `ExecutionOutcomeRecorder.record`, which the coordinator uses, moves the task, then closes the attempt, and only then reconciles the goal. A failed close there leaves the attempt open and the goal not reconciled. The two paths differ in this order.
- `ExecutionRecordRegistry.close_attempt` closes the latest open attempt of a task. When the task has no open attempt, it writes a new closed record with no start time, for a task that was running before records existed. A command that calls it without checking would add a record to a task that has none open.
- `ExecutionRecordRegistry.open_attempt` closes a stale open record as `abandoned` when a task is started again. A task that is `ready` therefore repairs itself at the next start, and only a final task cannot.
- `completed` and `failed` have no transition out, and `aic task requeue` accepts only a `running` task.
- `ArchiveEntry` refuses an open record, which is why the archive is refused. `aic validate` and `aic task history` report the state in the words quoted above.
- `aic goal status` reconciles the goal and writes it when it differs. It is not in `cli.READ_ONLY_COMMANDS`, so it takes the state lock.
- A run lock file can be left behind by a killed owner, and `aic task requeue` removes it when the owner is gone. The attempt of a coordinator run that was recorded in a failing write has no owner, because the process ended or released its lock.

## Requirements

1. It fixes only the state that this note describes: a final task with an open attempt. It does not touch any other state.
2. A person stays in control. Nothing closes an attempt by itself, and every write has a reason that a person gave.
3. The outcome that it writes is the one that the task already has, so no record says something that is false.
4. It adds no record. A task with no open attempt is refused, and `close_attempt` is not called for it.
5. It is safe to run twice, and a crash at any step leaves a state that it can finish.
6. It adds no field and no value to a state file, and no schema change.
7. The existing lifecycle does not change: the write order of the finish commands and the recorder stays as INV-16 says.

## Options

### Decision 1: how a person closes the attempt

**1A. A command, `aic task close-attempt <task-id> --reason "<text>"` (recommended).** It closes the open attempt of a task that is `completed` or `failed`. It is a new write path outside the normal lifecycle, which is why G11 was left open, and Decisions 2 to 4 make it as narrow as the lifecycle's own steps.

**1B. A fix option on `aic validate`.** `aic validate` is a read-only check and stays one. A writer that is named like a reader hides what it does. Rejected.

**1C. Close the attempt before the task moves.** The state after a failure would then be a closed attempt for a running task, which looks like a task that began before records existed, and nothing could see it. The order of INV-16 is what makes the left-open state visible. Rejected.

**1D. Let `aic task start` or `aic task requeue` accept a final task.** It would open a route out of a final state for the sake of a record. Rejected.

**1E. A general `aic repair` that fixes whatever `aic validate` finds.** It is too much power for one decision, and it would hide what it changed. One narrow command for each known state is easier to test and to explain. Rejected for now.

**1F. Keep the hand edit.** The edit writes `abandoned`, which is false, it needs a person to edit JSON, and it is the only way out today. Rejected.

### Decision 2: what the command accepts and refuses

**2A. It accepts a task whose status is `completed` or `failed` and which has exactly one open attempt (recommended).** Everything else is refused, with a message that says what to do, and nothing is written:

- a task that does not exist: the usual task-not-found error;
- a `running` task: `finish it with aic task complete, aic task fail or aic task requeue`;
- a `ready` or `pending` task: the task is not final, and the next `aic task start` closes a left-over attempt as `abandoned`;
- a final task with no open attempt: `task <id> has no open attempt`;
- a final task with more than one open attempt: the lifecycle cannot make this state, because starting a task closes the earlier attempt, so it came from a hand edit, and the command refuses it and says so.

**2B. Also accept a `ready` task.** The next start already does it. Rejected.

### Decision 3: what it writes

**3A. The outcome is the status of the task, the reason is the one that the person gave with a fixed beginning, and the time is the time of the repair (recommended).** The attempt gets `ended_as` equal to `completed` or `failed`, as the task has. The stored reason is `closed afterwards: <text>`, so that `aic task history` shows that the normal lifecycle did not close it. `ended_at` is the time at which the command ran. The reason is required and a blank one is refused before anything changes, as for `aic task requeue`. The command prints the task, the attempt, the outcome and the reason.

The time of the repair is what the file says when it was written. The time at which the task really moved is in `updated_at` of the task, and using it would be an inference. A duration that is computed from the record would then include the time that the attempt stayed open, which is a fact about the record.

**3B. `abandoned`.** It is what the hand edit writes. The task has an outcome, and `abandoned` says that it has none. Rejected.

**3C. A new value for `ended_as`, such as `repaired`.** It loses the outcome, and it adds a value that every reader of the file would have to know. Rejected.

**3D. Take the time from `updated_at` of the task.** Rejected, as above.

### Decision 4: the goal

**4A. The command does not reconcile the goal (recommended).** `aic goal status` already does it, and the state that needs it, the coordinator path of Evidence 3, can be fixed with that command. The message of the command does not mention it, because the state that it fixes does not need it. Decision 5 stops the coordinator path from leaving it.

**4B. The command reconciles the goal, so that one command fixes both.** It repeats what another command does, and the goal can also be wrong without any open attempt. If it did, it would have to reconcile before it closes the attempt, so that a crash between the two leaves a state that it can run on again. Rejected.

### Decision 5: the order in the coordinator

**5A. Reconcile the goal before the attempt is closed, as the CLI path does (recommended).** `ExecutionOutcomeRecorder.record` would call `reconcile_goal` right after the task moves and before `close_attempt`. A failed close then leaves the same state on both paths, a final task with an open attempt, and one command is enough. It is a fix with its own test, which fails on the old code. The rule of INV-16 stays: the task moves, and the attempt is closed after it.

**5B. Leave it.** Then the coordinator path needs two commands, and a person has to know which. Rejected.

### Decision 6: a run that is still alive

**6A. Ask the owner, as `aic task requeue` does (recommended).** If the owner of the attempt is alive, refuse with the message that the run is still alive. If it is gone, remove its lock file after the attempt is closed, and if it is unknown, do nothing more. The window in which an owner is alive for a final task is very short, because a run moves the task and closes the attempt in one entry of the state lock, which the command holds while it looks. The check costs little and keeps one rule for runs.

**6B. Do not ask.** A lock file that a killed owner left stays behind, and a run that is somehow alive is not seen. Rejected.

### Decision 7: where a person is told about the command

**7A. A hint in the note of `aic task history` and in the refusal of `aic goal archive`, when the task is `completed` or `failed`, and none in `aic validate` (recommended).** These are where a person meets the state and gets stuck. The note of `aic task history` would end with `close it with: aic task close-attempt <task-id> --reason "<text>"`, and the refusal of `aic goal archive`, which today says that the record is still open, would add the same line. `aic validate` names the record and the task in a line that tests pin, and it can be run for any reason, so it stays as it is. The earlier decision not to add a hint to `aic task status` stands.

**7B. No hint.** The command would have to be found in the help. Not recommended.

## Recommendation

Take 1A, 2A, 3A, 4A, 5A, 6A and 7A, in this order of work.

1. The recorder reconciles the goal before it closes the attempt, with a test that fails on the old order.
2. A function that decides what to do with a task and its attempt, and that writes, with its tests: the refusals of Decision 2, the outcome and the reason of Decision 3, no write for a refusal, and no record added for a task with no open attempt.
3. The command `aic task close-attempt`, with its classification as a locking command in the same commit, and its tests, which cover the lock, the owner of Decision 6, and running it twice.
4. The hints of Decision 7, with the existing tests of those messages pinned first.
5. The documentation, with the Windows record after the maintainer runs it, and the change of G11 in STATUS.

## What this does not do

- It does not make the finish commands atomic. A write can still fail between the two steps, and the state that follows is still seen by `aic validate`.
- It does not bring back a reason that was lost. The reason of `aic task complete --reason done` in Evidence 1 was stored nowhere, and the person gives a reason again.
- It does not repair a goal whose status is wrong with no open attempt. `aic goal status` does that.
- It does not close an attempt of a task that is not final, and it does not handle more than one open attempt.
- It does not run by itself, and it does not close several attempts at once.
- It does not protect against a person who edits `tasks.json` or `executions.json`, or against another program.

## Tests the build needs

- Each refusal of Decision 2 writes nothing and prints the message, and a task with no open attempt gets no new record.
- A `completed` task and a `failed` task get an attempt with `ended_as` equal to the status, a stored reason that begins with `closed afterwards: `, and an `ended_at` that is the time of the command. A blank reason is refused before anything changes.
- Only the attempt of that task changes, and the other records are byte for byte the same.
- Running the command twice gives the second refusal, that there is no open attempt, and changes nothing.
- An owner that is alive refuses, an owner that is gone has its lock file removed after the attempt is closed, and an unknown owner does nothing more. A lock file that cannot be removed does not stop the command.
- After the command, `aic validate` no longer reports the record and `aic goal archive` is no longer refused for it.
- A failed close in the coordinator leaves the goal reconciled, which fails on the old order, and the order tests for the finish commands and the recorder still pass.
- The command is not in `cli.READ_ONLY_COMMANDS` and takes the state lock, and a held state lock stops it with the usual error.
- The hints appear for a final task and not for a running one, and `aic validate` is unchanged.
- Mutations: the status check, the outcome taken from the status, the reason prefix, the check for no open attempt, the check for more than one, the owner check, and the order in the recorder are each caught.

## Risks

- **A new write path.** It is the reason that G11 was left open. The command is narrow, it needs a reason, it takes the outcome from the task, it refuses everything else, and it holds the state lock, as the lifecycle's own steps do.
- **A wrong outcome from a hand-edited state.** If a person set the status of a task by hand to something that its attempt does not match, the command would write that status. The command cannot know, and the reason says that the record was closed afterwards.
- **The time.** An attempt that was open for a long time gets a long duration. That is true of the record.
- **A message that tests pin.** The hint of Decision 7 changes the text of two messages, so the tests of those messages are pinned first and changed in their own commit.
- **Windows.** Nothing in the command is specific to a platform, but the failing write was only simulated, on Linux. A real unwritable file on Windows was not tried then, and it was tried later, as the record at the end of this note says.

## Open questions for the maintainer

Each has a recommendation, and the reply "continue with best" accepts them all.

1. Add the command `aic task close-attempt` (1A)? Recommendation: yes.
2. Take the outcome from the status of the task, and the time of the repair (3A)? Recommendation: yes.
3. Require a reason, and store it with the beginning `closed afterwards: ` (3A)? Recommendation: yes.
4. Leave the goal to `aic goal status` (4A)? Recommendation: yes.
5. Change the order in the coordinator's recorder so that the goal is reconciled before the attempt is closed (5A)? Recommendation: yes.
6. Ask the owner, refuse a live run and remove the lock file of a gone owner (6A)? Recommendation: yes.
7. Add the hints to `aic task history` and `aic goal archive`, and none to `aic validate` (7A)? Recommendation: yes.
8. Refuse a task with more than one open attempt, and say that it came from a hand edit (2A)? Recommendation: yes.

## Recommended order

1. Make the recorder reconcile the goal before it closes the attempt, with its test. Built.
2. Add the function that closes the left-open attempt, with its tests. Built.
3. Add the command and its classification in one commit, with its tests. Built.
4. Pin the messages of `aic task history` and `aic goal archive`, then add the hints. Built.
5. Write the documentation, with the Windows record after the maintainer runs it, and change G11 in STATUS. Done, with the record below.

## Record of the build

The reply "continue best" accepted the recommendation of every decision and the recommended answer to each of the eight open questions, and the reply that built the first step said that this was the assumption. Nothing in the decisions changed in the build. Two things in the plan did: an old test that pinned the lines of an open attempt as the last two lines of `aic task history` was reworked in its own commit before the hint code, written so that it passes before and after, and a `source=` argument that `close_attempt` ignores when an attempt is open was taken out of the new function, because a mutation test showed that nothing used it.

It was built in the order of the note, in two blocks that the maintainer ran on Windows:

| Step | Commit | What it is |
| --- | --- | --- |
| 1 | `8cfb9c2` | `ExecutionOutcomeRecorder.record` reconciles the goal before it closes the attempt |
| 1 | `7f90ea7` | Tests of that order |
| 2 | `6077734` | `execution/left_open.py`: `close_left_open_attempt` returns `ClosedLeftOpen` or raises `LeftOpenRefused` |
| 2 | `832961b` | Tests of the function |
| 3 | `42d9bf5` | `aic task close-attempt <task-id> --reason "<text>"`, classified as a command that takes the state lock in the same commit |
| 3 | `bdd6ae0` | Tests of the command |
| 4 | `a58bdc1` | The old pin of the lines of `aic task history` reworked |
| 4 | `32cf70e` | The hint in `aic task history` |
| 4 | `762bd58` | Tests of the hint |
| 4 | `f4bcaec` | The list of the tasks in the refusal of `aic goal archive` |
| 4 | `846ce25` | Tests of the list |

The command adds no field and no value to a state file, so there is no schema change. It finds the owner of the run in the way that `aic task requeue` does, and it removes the lock file of a gone owner after the close. `GoalArchiveError` now carries the tasks that have an open attempt, and the archiver refuses early for them with the same first line as before.

**What it does, run again for this record on Linux with the real CLI and the failing close simulated as in Evidence 1.** After `aic task complete --reason done` ended with `Error: executions.json cannot be written: simulated`, `aic validate` failed with the open record, and `aic task history` ended with the line `Close it with: aic task close-attempt <task id> --reason "<text>"`. `aic goal archive` refused with `Tasks with an attempt that was left open: 1`, the task id and the line `Close each with: aic task close-attempt <task-id> --reason "<text>"`, and then `Nothing was changed.` The command printed `Attempt closed: <attempt id>`, the task, `Outcome: completed` and `Reason: closed afterwards: <the reason>`, and exited 0. Run again, it printed `Error: task <id> has no open attempt.` and exited 1. After the close `aic validate` printed `Validation passed.`, `aic task history` showed the outcome `completed` with the reason `closed afterwards: <the reason>`, and `aic goal archive` succeeded.

**How it was checked on Linux.** These figures were recorded when the steps were built, and they were not run again for this record.
- Step 1: three tests of the recorder fail on the old order and pass on the new one. The order tests of the finish commands and of the recorder, which INV-16 describes, still pass.
- The first block (the recorder, the function and the command): 19 mutations were all caught, and 13 of 13 tests of the command fail when the command is missing. A mutation that survived at first was a `source=` argument that `close_attempt` ignores when an attempt is open. It was a dead argument and was removed.
- The second block (the hints): 14 mutations were all caught, and three of the tests of `aic task history` and six of the tests of the archive fail on the old code.
- A comparison of the old and the new code on the same commands, with ids, times and paths masked, gave identical output and exit status for 10 commands in the first block and for 9 commands in the second.
- The real CLI was run with the failing close simulated, as in Evidence 1 and 3.

**On Windows.** The maintainer ran the full suite under Git Bash before each commit. The first block gave 1312, 1315, 1315, 1337, 1337 and 1350 passed, and the second gave 1350, 1350, 1356, 1356 and 1366 passed, each with 2 skipped. The last run was on the tree that became the commit `846ce25`. The suite has 1368 tests, and the two that are skipped on Windows are the ones that can run only on a POSIX system.

The maintainer then ran a script on Windows under Git Bash, with Python 3.14.3, in a temporary data directory, that made `executions.json` read-only for real. Nothing was patched, and nothing tracked was changed. It had 17 checks with an expected answer, which all came out as expected, and 3 observations:
- `aic task complete` on a started task exited with status 1, after about half a second. The task was then `completed`, its attempt was still open, and `aic validate` failed.
- `aic task history` showed the hint, and `aic goal archive` listed the task and changed nothing.
- `aic task close-attempt` while the file was still read-only exited with status 1 and left the attempt open.
- After the file was writable again, the command exited 0 with the outcome `completed`, `aic validate` passed, and `aic goal archive` succeeded.

**A new finding, G25.** The commands that were refused because the file was read-only ended with a Python traceback and not with an `Error:` line. The last line was `PermissionError: [WinError 5] Access is denied`, and it named the temporary file and `executions.json`. The cause is in the code and not in this command: `write_text_atomic` raises the error again after it removes its temporary file, and `main` catches only `StateFileError` and `StateLockError`. It is recorded as G25 in [STATUS.md](STATUS.md) and is not fixed here. It could not be reproduced on Linux without patching, because `os.replace` onto a read-only file succeeds there.

**What this changes in the note.** The sentence in Evidence that a real unwritable file was not observed on any platform was true when the note was written, and a real one was observed later on Windows, as above. The risk that is named under Windows is answered in the same way: the failing write was only simulated on Linux, and then it was real on Windows.

**Not known.** A real crash between the two writes, as opposed to a failed write, was not made on any platform. A network file system and Python 3.11 were not tried. What the command does with a state that was edited by hand in ways other than the ones in the tests was not tried either.
