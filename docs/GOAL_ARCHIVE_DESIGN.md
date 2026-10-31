# Design Note: Taking Finished Goals Out of the Active State

**Status: Proposed. Not accepted, and no code is written.** Everything below the evidence is a recommendation for the maintainer to accept, change or reject. Nothing was run on Windows for this note.

## Problem

`aic project remove` refuses a project that a goal still names ([ARCHITECTURE.md](ARCHITECTURE.md), gap G20 in [STATUS.md](STATUS.md)). The goal commands are `create`, `list` and `status`. There is no way to remove a goal, so a project that has ever had a goal stays registered for good, even when all of its work is finished. A project registered by mistake, and then used once, cannot be taken out. A project whose directory was deleted and whose goals are all finished still fails `aic validate` until the directory is put back (G15).

The obvious answer, a command that deletes a goal, is the one answer that has to be examined before it is built. A goal is the top of a chain. Its tasks name it, and the execution records name the tasks. Deleting the top of the chain either leaves the rest pointing at nothing or deletes the audit trail with it.

## Evidence

All of this was run on Linux, with the real CLI and a temporary data directory. Nothing here was run on Windows.

- A project `app` was registered, one goal was created for it, and two tasks were created for the goal. The first task was marked ready and run with the `noop` target, which completed it and wrote one execution record. The second task was marked ready. `aic goal list` showed the goal as `in_progress`, and `aic validate` printed `Validation passed.`
- The goal was then removed from `goals.json` by hand, which is the only way to remove one today. `aic validate` printed `Validation failed.` and one line for each task, `Task <id> references missing goal: <goal id>`, and exited 1.
- `aic task list` still listed both tasks. `aic task history` of the completed task still printed its attempt. Running the second task printed `Result: rejected` and `Reason: parent goal not found` and exited 1.
- `aic project remove app` then succeeded, because no goal named the project any more.

So a goal that is deleted by hand leaves tasks and records that no command can finish or explain, and the state fails validation.

## Facts about the current code

- A goal names its project by name. A task names its goal by id. An execution record names its task by id. A grant names a project and a target and does not name a goal.
- `aic validate` reports a task whose goal does not exist and an execution record whose task does not exist.
- The status of a goal is derived from its tasks: `pending`, `in_progress`, `completed` or `failed`. A task ends as `completed` or `failed`, and a `running` task has an open execution record.
- Each registry is its own file, `goals.json`, `tasks.json` and `executions.json`, written atomically one file at a time. There is no write that covers two files, which is why the write order rule (INV-16) exists for the start and the end of a run.
- Every command that writes takes the state lock for the whole command, apart from `aic task run`, which locks around its state operations only.

## Requirements

1. A project whose work is all finished can be removed.
2. Nothing that records what was done is destroyed. The execution records exist so that a later reader can see what ran, with which target, and how it ended.
3. After the command, the active state passes `aic validate`: no task without a goal, no record without a task.
4. A crash between two writes leaves a state that a person can see and that the same command can finish.
5. A goal that has work in flight, a task that is `ready` or `running`, is never taken out.
6. If a project name is registered again later for another directory, the old history does not silently attach to the new directory. This is the reason that names are unique, and `aic project remove` already refuses what would break it.

## Options

**1A. Archive finished goals (recommended).** A new command moves a finished goal, its tasks and their execution records out of the three active files and into an append-only archive file. The active state is then smaller and valid, and the history is kept, in one place, with the project's name and directory as they were. `aic project remove` looks only at the active goals, so archived goals do not block it.

**1B. Delete a goal and everything under it.** One command removes the goal, its tasks and their records. It is the simplest to build and the simplest to explain. It destroys the audit trail, which is the one thing that AIC exists to keep. It is rejected.

**1C. Delete only a goal that has no tasks.** This is safe, because nothing refers to such a goal. It is rarely useful, because a goal that was worked on has tasks. It does not close G20 for the case that matters. It is rejected as the answer, though it is what the archive command does for a goal that has no tasks.

**1D. Let `aic project remove` ignore finished goals.** The project would be removable while its finished goals still name it. `aic validate` would then have to tolerate a goal whose project is not registered, which weakens the project reference rule (the closed gap G3), and a name that is registered again later would attach the old goals to a different directory. This breaks requirement 6. It is rejected.

**1E. Do nothing.** G20 stays documented, and a project that has had a goal stays registered. It costs nothing and is honest. It is the right choice if removing projects is not something that is needed. It is not recommended, because the first wrongly registered directory with a goal has no repair other than editing three files by hand.

## Recommendation

**Decision 1: archive, not delete (1A).** The command is `aic goal archive <goal id> --reason <text>`.

**Decision 2: what can be archived.** A goal whose tasks are all `completed` or `failed`, and a goal that has no tasks. A goal with any task that is `pending`, `ready` or `running` is refused, and the refusal lists those tasks and the status of each. There is no `--force`, so no flag can take work in flight out of the active state. A goal that is refused changes nothing.

**Decision 3: where the history goes.** One file, `archive.json`, beside `tasks.json`, in the same versioned format as the other state files (`{"schema_version": 1, "archived": [...]}`). Each entry holds the goal, its tasks, their execution records, the time of archiving, the reason, and the project's directory as the registry had it at that moment, or no directory if the project is not registered. The directory is what keeps requirement 6: the entry says which directory the name meant when the work was done. The file is only ever appended to by this command. Nothing reads it back into the active state.

**Decision 4: the write order.** The entry is written to `archive.json` first. Then the execution records are removed from `executions.json`, then the tasks from `tasks.json`, then the goal from `goals.json`. Each of those is one atomic file write. A crash after the first write leaves the work in both places. A crash after a later write leaves a goal with fewer tasks, or a task without records, and every one of those states is valid for the active files. In every case `aic validate` reports a goal that is both active and archived, and running the same command again finishes the job, because an entry that is already in the archive is not written twice. The rule is the same as INV-16: the copy that is kept is written before the original is removed.

**Decision 5: `aic project remove` is not changed.** It already counts only the goals in `goals.json`. After a goal is archived it stops blocking, with no new code in the project commands. The archive entry keeps the name and the directory, so the history stays unambiguous when the name is registered again.

**Decision 6: the command locks.** `aic goal archive` is a state-changing command and takes the state lock for the whole command. Its entry in the command classification is added in the same commit as the parser entry, as the rule for new commands says.

**Decision 7: a read-only listing comes after.** Once the history is out of the active files, `aic task history` cannot show it. A later stage adds `aic goal archived`, which lists what was archived, with the goal, its status, its project and directory, the reason, and the number of tasks and records. It does not change any file. Restoring an archived goal is not designed, and the data is kept whole so that it can be.

**Rejected inside the decisions:** a `--force` that archives work in flight; moving only the goal and leaving the tasks; moving the records and not the tasks; a second archive file for each of the three kinds, which would lose the link between them; keeping the archive in the same file as the active state, which would make every command read all of the history.

## What this does not do

- It does not delete anything. The history moves, and it is kept.
- It does not remove a project. `aic project remove` does that, and only when nothing active names the project.
- It does not archive a goal with work in flight, and it has no flag that does.
- It does not restore, edit or search the archive. A person can read the file.
- It does not make the archive tamper-evident. Like every state file, it can be edited by anyone who can edit the data directory.
- It does not limit the size of the archive or expire anything.

## Tests the build needs

- A goal with only finished tasks is archived: the goal, the tasks and the records are gone from the active files, one entry is in the archive, and `aic validate` passes.
- A goal with no tasks is archived with an entry that has no tasks and no records.
- A goal with a `pending`, `ready` or `running` task is refused, the refusal lists those tasks, and no file changes.
- An unknown goal id is refused. A blank reason is refused.
- The archived entry holds the project name and the directory that the registry had, and holds no directory when the project is not registered.
- After the archive, `aic project remove` succeeds for a project whose only goals were archived, and still refuses a project that has an active goal.
- Archiving the same goal twice does not write a second entry. A state that has the goal in the archive and still active is reported by `aic validate`, and running the command again completes it.
- A failed write to each of the four files, one at a time, leaves a state that `aic validate` reports and that the same command repairs.
- The command is classified as a command that locks for the whole command, and the test that every parser command is classified passes.
- An archive file that cannot be read gives `Error: <path> cannot be read: <reason>`, as the other state files do, and does not overwrite the file.
- The archive is read with the reader that tells an absent file from an unreadable one, because the rule that an unreadable file is never read as an empty one applies here too.

## Risks

- **The archive grows without limit.** Nothing expires. This is chosen on purpose, because the point is to keep the history, and the file is not read by the commands that run every day.
- **A crash leaves a partly moved goal.** The write order makes every state valid and visible, and the command is safe to run again. It cannot make the four writes one write.
- **The history leaves the places where the commands look for it.** After archiving, `aic task history` no longer finds the tasks. This is why a listing is a stage of its own, and it is a cost of choosing 1A.
- **Two commands can be run in a row without the person seeing why the second one succeeds.** Archiving is what unblocks the removal of the project. The refusal from `aic project remove` already says that goals cannot be removed yet, and it would be changed to point at the archive command once that exists.
- **No Windows observation.** The file handling is the same as for the other state files, and no Windows run was made for this note.

## Open questions for the maintainer

1. **Archive instead of delete?** Recommended: yes, 1A. The alternative that is shorter to build, 1B, destroys the history.
2. **Only finished goals, with no `--force`?** Recommended: yes.
3. **A required reason?** Recommended: yes, as for a grant, so that the archive says why each goal was taken out. A blank reason is refused.
4. **One archive file beside `tasks.json`?** Recommended: yes.
5. **The listing `aic goal archived` as a later stage, and no restore for now?** Recommended: yes.
6. **Should `aic project remove` offer to archive the goals for the person?** Recommended: no. Two explicit commands show what each one does, and the removal command stays one that only removes an entry.

## Recommended order

1. The archive file and its registry as a library, with tests, including the write order and the unreadable file.
2. `aic goal archive`, its classification as a locking command, the check in `aic validate` for a goal that is both active and archived, and tests through the CLI with the real registries.
3. The change to the refusal of `aic project remove`, so that it points at the archive command.
4. `aic goal archived`.
5. The documentation, and the Windows record.
