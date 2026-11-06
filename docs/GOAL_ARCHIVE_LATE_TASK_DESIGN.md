# Design Note: A Task Cannot Be Added to a Goal Whose Archive Was Interrupted

**Status: Proposed. Not accepted.** This note decides what to do about G21, a goal that was archived halfway and then got a new task, which the command that archives it cannot finish. It follows [GOAL_ARCHIVE_DESIGN.md](GOAL_ARCHIVE_DESIGN.md). The evidence was observed on Linux with the real CLI and a simulated crash, and nothing in it was run on Windows. Nothing is built.

## Problem

`aic goal archive` writes the archive entry first, and then removes the records, the tasks and the goal from the active files, one atomic write each. A crash in between leaves a valid state, and archiving the goal again finishes it. G21 says that this breaks when a task is added to the goal in between. The command then refuses with `already archived, but task <id> is not in the archive`, `aic validate` keeps reporting the goal, and the only way out is to edit `tasks.json` by hand. G21 was shown by a test only. This note asks whether the CLI can really reach that state, and what is the smallest change that fixes it.

## Evidence

All of this was run on Linux, with the real CLI and a temporary data directory. The only simulated part is the crash: a script made the last write of the archiver, the removal of the goal, raise an error, as the existing test does. A real crash was not made.

1. **A goal that had finished tasks cannot get a late task.** After the simulated crash, `aic validate` printed `Validation failed.`, with three lines for that goal. One said `status mismatch: persisted=completed, derived=pending`, because its task was already removed. Another said `is archived and also still active; finish it with: aic goal archive <goal id> --reason <text>`. `aic task create --goal <id>` was refused with `Cannot create task for completed goal`. Running `aic goal archive` again printed `Goal archive finished`, `An earlier attempt had written the archive entry, and its reason is kept`, and archived the one task.
2. **A goal that had no tasks can get a late task.** After the same simulated crash, the goal was still `pending`. `aic task create --goal <id>` printed `Task created.` The task was `pending`. `aic goal archive` then printed `goal <id> is already archived, but task <task id> is not in the archive` and `Nothing was changed.` `aic validate` kept printing `is archived and also still active`. No command removes the task, so the state cannot be left without editing a file.
3. **A goal with no tasks can be archived on purpose.** The rules of the archive say that a goal is archivable when every task is finished or when it has no tasks. A goal that was planned and then dropped is an example.

## Facts about the code

- `create_task` in `tasks/commands.py` reads the goal, calls `validate_task_creation(goal)`, and then adds the task. `validate_task_creation` refuses an unknown status, a `completed` goal and a `failed` goal. A `pending` or `active` goal is accepted.
- The status of a goal is stored, and it is changed only when tasks are added or change status. Removing the tasks of a goal during archiving does not change the stored status, so a goal that had finished tasks stays `completed` or `failed` until it is removed. This is why evidence 1 is refused.
- `GoalArchive.get_entry(goal_id)` returns the entry or None, and an absent archive file is an empty archive. A file that cannot be read raises the error that the CLI already prints as `Error: ...` with status 1.
- `GoalArchiver.archive_goal` refuses a goal that has an entry when one of its tasks is not in that entry, and the entry is append-only. `ArchiveEntry` refuses unfinished work, so a late task that is `pending` cannot be added to an entry.
- `create_task` is the only command that adds a task. The other task commands change a task that exists, and a goal that has an entry and no tasks has none to change.
- A command that adds a task takes the state lock for the whole command, as every command that writes does.

## Requirements

1. After the fix, no sequence of CLI commands leaves a goal that is both archived and holding a task that is not in the archive.
2. Nothing is deleted. The archive stays append-only, and no task is removed without a record.
3. Archiving a goal that was interrupted still finishes with the first entry and the first reason.
4. The message says what is wrong and which command finishes the job.
5. Goals that have no entry are not affected, and neither is a project that has an archive.
6. No new command, and no change to the format of any file.

## Options

### Decision 1: where to close the window

**1A. `aic task create` refuses a goal that has an archive entry (recommended).** The window can only be opened by adding a task, and this closes it at the one place where tasks are added. The message tells a person to finish archiving the goal.

- Pro: small. It reads one file that the archive already uses, and it changes no data format and adds no command.
- Con: one more file is read when a task is created.

**1B. Let `aic goal archive` take the late task into the entry.** A late task is `pending`, and an entry refuses work in flight, so the rules of the archive would have to change. Rejected.

**1C. Remove the late task so that the archive can finish.** It deletes a task that the person made, with no record of it. Rejected, because the archive was made so that nothing is destroyed.

**1D. A repair command for a goal in this state.** A command for a state that cannot be reached any more is a command to keep. If a goal is already stuck, hand editing is the way, and no stuck goal is known. Rejected for now.

**1E. Make a goal that has no tasks `completed` when archiving starts.** It changes the stored status and the rules of every command for a case that one refusal covers. Rejected.

**1F. Refuse to archive a goal that has no tasks.** It removes a use of the archive that is allowed on purpose (evidence 3). Rejected.

**1G. Leave it and document it.** It is a crash between two writes, in a goal that had no tasks, followed by a task that is created for that goal. It is rare, but the way out is to edit a file, and the fix is a few lines. Not recommended.

### Decision 2: which message comes first

A goal that has an entry and is `completed` would be refused with `Cannot create task for completed goal`, which does not say how to fix anything.

**2A. Check the archive before the status, so that the message says how to finish (recommended).** For example `Error: goal <id> is already archived, and the archive was not finished; finish it with: aic goal archive <id> --reason <text>`.

**2B. Check the status first.** A goal with finished tasks would say that it is completed, and a goal with no tasks would say that it is archived. It is correct and less useful. Rejected.

### Decision 3: what else changes

**3A. Nothing else (recommended).** `aic validate` already says how to finish an interrupted archive. Its line `status mismatch: persisted=completed, derived=pending` is true, because the tasks are gone, and it goes away when the archive is finished (evidence 1). The archiver, the archive file and the other commands are not changed.

## Recommendation

Take 1A, 2A and 3A. In `create_task`, after the goal is found and before its status is checked, ask the archive whether the goal has an entry, and if it has, print the error and return 1 without writing anything.

    aic task create --goal <id> "late task"
    Error: goal <id> is already archived, and the archive was not finished; finish it with: aic goal archive <id> --reason <text>

## What this does not do

- It does not repair a goal that is already in the stuck state. None is known, and a real crash was not made.
- It does not make the archive crash-proof. It makes the one state that cannot be left by a command impossible to reach.
- It does not change `aic validate`, the archive, or any file format.

## Tests the build needs

- Creating a task for a goal that has an archive entry is refused with the message of Decision 2, the exit status is 1, and `tasks.json` is not changed. This holds for a goal with no tasks and for a goal whose stored status is `completed` or `failed`, and the message is the same for both.
- Creating a task for a goal that has no entry still works, with an archive file that is absent, that holds the entry of another goal, and that holds the entries of other goals of the same project.
- With the real registries and a last write that fails, as in the existing test: archive a goal that has no tasks, then try to create a task, which is refused, then archive again, which finishes, and then `aic validate` passes. The same for a goal with tasks.
- An archive file that cannot be read gives the same error that other commands give, and creates no task.
- The classification of `aic task create` is unchanged: it locks, and it is not a read-only command.
- Mutations: ask for the wrong goal, skip the check, check after the status, and allow a goal with an entry when it has no tasks, are each caught.

## Risks

- **One more read.** A task is created with one more file read. A goal archive is small, and a missing file is cheap.
- **A goal that is stuck already.** If one exists, it stays stuck, and the message of `aic validate` stays what it is. The recommendation is to leave it, because none is known.
- **The message can be wrong if the entry is wrong.** It trusts the archive file, as the other archive commands do. The archive is plain JSON and not tamper-evident.
- **Windows was not observed.** The check reads a file and compares text, so no difference is expected, but it was not run there.

## Open questions for the maintainer

Each has a recommendation, and the reply "continue with best" accepts them all.

1. Make `aic task create` refuse a goal that has an archive entry (1A)? Recommendation: yes.
2. Check the archive before the status, so that the message says how to finish (2A)? Recommendation: yes.
3. Leave states that already exist to hand editing, with no repair command (1D)? Recommendation: yes, because none is known.
4. Keep archiving a goal that has no tasks (reject 1F)? Recommendation: yes.
5. Leave the `status mismatch` line of `aic validate` as it is (3A)? Recommendation: yes.

## Recommended order

1. Add the tests that fail now: a goal with an entry gets a task.
2. Add the check in `create_task`, with its message.
3. Write the documentation, with the Windows record after the maintainer runs it, and close G21 in STATUS.
