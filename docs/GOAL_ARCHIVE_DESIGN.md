# Design Note: Taking Finished Goals Out of the Active State

**Status: Accepted as recommended; all three stages are built.** The maintainer accepted all six recommendations in the open questions. The evidence below was run on Linux before anything was built, and nothing in it was run on Windows. What the built stages did is in the sections Stage 1: built, Stage 2: built and Stage 3: built at the end. A view of the tasks and the attempts of one archived goal was not part of this design, and was added by [GOAL_ARCHIVE_DETAIL_DESIGN.md](GOAL_ARCHIVE_DETAIL_DESIGN.md).

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

The maintainer accepted all six recommendations below.

1. **Archive instead of delete?** Recommended: yes, 1A. The alternative that is shorter to build, 1B, destroys the history.
2. **Only finished goals, with no `--force`?** Recommended: yes.
3. **A required reason?** Recommended: yes, as for a grant, so that the archive says why each goal was taken out. A blank reason is refused.
4. **One archive file beside `tasks.json`?** Recommended: yes.
5. **The listing `aic goal archived` as a later stage, and no restore for now?** Recommended: yes.
6. **Should `aic project remove` offer to archive the goals for the person?** Recommended: no. Two explicit commands show what each one does, and the removal command stays one that only removes an entry.

## Recommended order

1. **Built.** The archive file and its registry as a library, with tests, including the write order and the unreadable file.
2. **Built.** `aic goal archive`, its classification as a locking command, the check in `aic validate` for a goal that is both active and archived, and tests through the CLI with the real registries.
3. **Built.** The change to the refusal of `aic project remove`, so that it points at the archive command.
4. **Built.** `aic goal archived`.
5. The documentation, and the Windows record.


## Stage 1: built

Stage 1 of the recommended order, the archive file and its registry as a library, is built in four commits, with no command yet.

- **The entry.** `ArchiveEntry` in `goals/archive.py` holds a goal, its tasks, their execution records, the time, the reason and the project directory that the registry had, or none. It enforces the rules of Decision 2 itself, as a second wall under the command: a blank reason, a task of another goal, a task that is `pending`, `ready` or `running`, a record of a task that is not in the entry, an open record, and a task or a record listed twice are all refused. An entry is read-only once made.
- **The file.** `GoalArchive` stores `archive.json` beside `tasks.json` in the versioned state format, with the list called `archived`. It is read with the reader that tells an absent file from an unreadable one, so a file that cannot be read is an error and is never overwritten, and a newer schema version is refused and kept. The rules of an entry are applied to what is read as well, so an entry in the file that holds work in flight is invalid. `add_entry` returns `False` and writes nothing when the goal is already archived, and the entry that is there is kept, because it was made before anything was removed.
- **Tests.** There are 31 new tests, 15 for the entry and 16 for the file. One of them makes `Path.exists()` answer no for the file and checks that the entries are still found, because whether the file is there is decided by reading it.
- **Found while building.** The first mutation run left three of 29 mutations alive: a blank archive time, and lists that were not made tuples, which would make an entry unhashable. Two tests were added, and all 29 were then caught.
- **Windows.** The maintainer ran the full suite on Windows under Git Bash before each of the four commits, which gave 963, 978, 978 and 994 passed, each with 2 skipped. The last run was on the tree that became `51a040b`.

## Stage 2: built

Stage 2 and the change of Stage 3 of the recommended order that concerns the refusal of `aic project remove` are built, in ten commits.

- **Removing from the active files.** `GoalRegistry.remove_goal`, `TaskRegistry.remove_tasks` and `ExecutionRecordRegistry.remove_records` each remove from one file with one atomic write, and write nothing when there is nothing to remove, including when the file is not there. Only archiving uses them.
- **The archiver.** `GoalArchiver` in `goals/archiving.py` follows Decision 4. It writes the entry first, then removes the records, then the tasks, then the goal. A goal that has a task that is not finished is refused, with the tasks listed, and nothing is written. A blank reason is refused even for a goal that is already archived. A goal that is already archived and no longer active is reported as done and nothing changes. When an earlier attempt left the entry in the archive, the second attempt keeps that entry and its reason and only finishes the removal. The project directory is taken from the registry, and is none when the project is not registered or the name has two directories.
- **`aic validate`.** A goal that is both active and archived is reported as `Goal <id> is archived and also still active; finish it with: aic goal archive <id> --reason <text>`, and a goal that is in the archive twice is reported too. The check applies when an archive registry is given, and the CLI gives one.
- **The command.** `aic goal archive <goal id> --reason <text>` needs the reason. It prints what moved, the project and its directory, the reason and the path of the archive, and says that nothing was deleted. It takes the state lock for the whole command, and its entry in the classification is in the same commit as the parser entry. A refusal says `Nothing was changed.`
- **The project removal refusal.** `aic project remove` still counts only the goals in `goals.json`. Its refusal now says that goals cannot be removed and names `aic goal archive <goal id> --reason <text>`, when a goal is what blocks it, and does not name it when only a grant does. The test that asserted the old wording was changed first, so that it passed before and after.
- **Observed on Linux, with the real CLI and a temporary data directory.** A goal with a `ready` task was refused with `Nothing was changed.` A run without `--reason` was a usage error. Before the archive, `aic project remove` refused the project. After `aic goal archive <id> --reason "all shipped"` the goal, its two tasks and their two records were gone from the active files, `aic validate` printed `Validation passed.`, and `archive.json` held one entry with two tasks, two records, the reason and a project directory that exists. Archiving the same goal again exited 0 and changed nothing. `aic project remove` then succeeded, and the directory and its files were not touched. `aic task history` of an archived task no longer finds the task, which is the cost that Stage 3, the listing, is for.
- **Tests.** There are 52 new tests: 10 for the removal methods, 20 for the archiver, 9 for validation and 13 for the command. The archiver tests make each of the four writes fail in turn, as a crash would, and check that the state is valid and reported and that archiving again finishes it with the same final state. They also show that removing the goal first fails five of them, so the write order is enforced.
- **Found while building.** Three of my own tests were wrong and the code was right: one expected the earlier reason after a crash at the very first write, when nothing had been archived yet; one made a `pending` goal with a `completed` task, which tripped an existing status rule; and one line was too long. The first mutation run left five of 33 alive: `remove_tasks` and `remove_records` writing when nothing was removed, a blank reason for an already archived goal, the "and N more" boundary at exactly five unfinished tasks, and a goal id with spaces around it. Five tests were added, and all 33 were then caught. One case is not covered by the design: a task added to a goal after a crash left it archived and still active stopped the second attempt (G21 in [STATUS.md](STATUS.md)). That was fixed later, as that note records.
- **Windows.** The maintainer ran the full suite on Windows under Git Bash before each of the ten commits, which gave 994, 1004, 1004, 1024, 1024, 1033, 1033, 1046, 1046 and 1046 passed, each with 2 skipped. The last run was on the tree that became `0012585`. A run of `aic goal archive` through the real CLI on Windows was not made then. It was made later, and the record is in [STATUS.md](STATUS.md), in the paragraph that begins `After the Python syntax check the maintainer ran a script on Windows`.

## Stage 3: built

Stage 3 of the recommended order, the read-only listing `aic goal archived`, is built, in two commits.

- **The listing.** `aic goal archived` prints every archived goal, oldest first and with no limit: the goal id, the project, the directory that the registry had or `not recorded`, the status, the description, the time, the reason, and the number of tasks and of execution records. It changes no file, does not create `archive.json` when it is not there, and says `No archived goals.` with exit status 0 when the archive is empty or absent. An archive that cannot be read is an error with exit status 1, and the file is kept as it was. It does not show the tasks or their attempts.
- **The classification.** The command is in the read-only set in `cli.py` and in the locking test, so it does not take the state lock. My first attempt put it only in the test, and `test_every_parser_command_is_classified` failed before anything was committed. A read-only command that is not in `READ_ONLY_COMMANDS` takes the lock, which is safe and wrong.
- **Observed on Linux, by hand, with a temporary data directory.** With no archive it printed `No archived goals.`, exited 0 and created no file. After one goal was archived with the reason `all shipped` it printed that goal with its project, its directory, `Status: completed`, `Tasks: 1` and `Execution records: 1`, and the checksums of the five state files were the same after listing. With the archive file replaced by invalid JSON it printed `Error: <path> is not valid JSON: ...`, exited 1, and the file was unchanged.
- **Tests.** There are 8 new tests, which run the command through the CLI. They include a goal whose project was not registered, six goals in order, the directory that is still the original one after the project is removed and the name is registered again for another directory, and a goal with 3 tasks and 1 record, so that the two counts are told apart.
- **Found while building.** The first mutation run left two of 16 alive: swapping the count of tasks with the count of records could not be seen, because my test goal had as many records as tasks. A test with 3 tasks and 1 record was added, and all 16 were then caught. Three of my own mutation anchors matched more than once, because `aic goal list` prints similar lines, and were made specific.
- **Added later.** A view of the tasks and their attempts for one archived goal was not part of this design. When Stage 3 was built, `aic task history` no longer found an archived task, and its attempts could be read only in `archive.json`. That is why it has its own design note, [GOAL_ARCHIVE_DETAIL_DESIGN.md](GOAL_ARCHIVE_DETAIL_DESIGN.md), which is accepted and built. A gap that was found in the way a crash can leave a goal, G21, has its own note, [GOAL_ARCHIVE_LATE_TASK_DESIGN.md](GOAL_ARCHIVE_LATE_TASK_DESIGN.md), which is accepted and built.
- **Windows.** The maintainer ran the full suite on Windows under Git Bash before each of the two commits, which gave 1046 and 1054 passed, each with 2 skipped. The last run was on the tree that became `fe42772`. A run of `aic goal archived` on Windows was not made then. It was made later, and the record is in [STATUS.md](STATUS.md), in the paragraph that begins `After the Python syntax check the maintainer ran a script on Windows`.
