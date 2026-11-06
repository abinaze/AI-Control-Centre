# Design Note: Reading the History of an Archived Goal

**Status: Accepted as recommended, and built.** The maintainer accepted all six recommendations in the open questions. It extends [GOAL_ARCHIVE_DESIGN.md](GOAL_ARCHIVE_DESIGN.md), whose three stages are built. The evidence below was run on Linux before anything was built, and nothing in it was run on Windows. What the built stages did is in the sections Stage 1: built and Stage 2: built at the end.

## Problem

Archiving moves a finished goal, its tasks and their execution records out of the active files. That was chosen so that the history is kept and not deleted. It is kept in `archive.json`, and `aic goal archived` lists each archived goal with the number of its tasks and of its records. No command shows the tasks themselves or the attempts, which are what the execution records exist to say: what ran, with which target, when, and how it ended. After archiving, `aic task history` and `aic task status` no longer find an archived task. The only way to read the history is to open the JSON file.

A history that can only be read by opening a file is kept, but it is not usable. The gap is recorded as G20 in [STATUS.md](STATUS.md).

## Evidence

All of this was run on Linux, with the real CLI and a temporary data directory. Nothing here was run on Windows.

- A project `app` was registered. One goal was created for it, with two tasks. The first task was marked ready and run with the `noop` target, which completed it. The second task was marked ready, started and failed with the reason `gave up`.
- Before archiving, `aic task history` of the first task printed `Status: completed`, `Attempts: 1`, and for the attempt a route of `coordinator (noop)`, the start and end times, `Outcome: completed` and the reason `noop adapter: no work was done`.
- The goal was then archived with `aic goal archive <id> --reason "all shipped"`. `aic task history` and `aic task status` of the same task each printed `Error: task not found: <task id>` and exited 1.
- `archive.json` held, for that goal, both tasks with their status and title, and both records, one from the `coordinator` route with the target `noop` and the outcome `completed`, and one from the `cli` route with no target, the outcome `failed` and the reason `gave up`. Every task had a record. Nothing was lost, and nothing could be shown.

## Facts about the current code

- `aic task history <task id>` reads the task from `tasks.json` and its attempts from `executions.json`, and prints the task, its status, the number of attempts, and for each attempt the route, the start, the end, the outcome and the reason. It prints a note when an attempt is still open and the task is not running.
- An entry in the archive cannot hold an open attempt, or a task that is not finished (INV-49). The attempt that is open is therefore never part of what an archived goal shows.
- `aic goal archived` takes no argument. It is in the read-only set under the name `goal archived`, so it does not take the state lock.
- The archive is read with the reader that tells an absent file from an unreadable one, and an archive that cannot be read is an error and is kept as it was (INV-50).
- Commands print text that people typed, such as a reason, a title or a description, as it is.

## Requirements

1. A person can read the tasks and the attempts of an archived goal, in the same form that `aic task history` shows them.
2. The command changes no file and takes no lock.
3. What is shown comes from the archive only. An archived goal is never mixed with the active state, so a person can tell at a glance that nothing shown can be acted on.
4. The two ways of showing an attempt cannot drift apart.
5. A goal that is not archived is refused with a message that says why, and the message tells an active goal from an unknown one.

## Options

**1A. Give `aic goal archived` an optional goal id (recommended).** With no argument the command lists the archive, as it does now. With a goal id it shows that goal as the listing does, and then its tasks, each with its attempts in the form of `aic task history`. The command is read-only already, and it keeps the archive in one place.

**1B. Let `aic task history` and `aic task status` look in the archive when they do not find a task.** A person who has a task id from an old log gets the answer from the command that they already use. It changes two commands that today read only the active state, so that "task not found" would sometimes mean "found in the archive", and a task that can be shown could be one that cannot be started or changed. It is rejected for now, and it can be added later if it is missed.

**1C. Export the archive as JSON from a command.** It serves other programs, not a person who wants to read. The file is already JSON. It is not needed now.

**1D. Show everything in the listing.** The listing would print every task and every attempt of every archived goal. It grows with the archive, and it hides the overview that the listing is for. It is rejected.

**1E. Do nothing.** The history stays in the file. It costs nothing, and it keeps a feature, archiving, that stores what it cannot show. It is not recommended.

## Recommendation

**Decision 1: an optional goal id on `aic goal archived` (1A).** The command name does not change, so its classification as read-only does not change.

**Decision 2: what is shown.** The goal as the listing shows it, then the tasks in the order that they were archived, each with its id, its status, its title, its description when it has one, and its attempts. A task that has no attempt says `No attempts recorded.` The attempts use the same lines as `aic task history`: the route, the start, the end, the outcome and the reason. The text that prints an attempt is moved into one function that `aic task history` and this command both call, so that the two cannot drift.

**Decision 3: the id.** The id is matched exactly, after trimming, as every other command matches an id. A goal that is not in the archive is refused with `Error: goal <id> is not archived` and exit status 1. A goal that is in the active files is refused with `Error: goal <id> is not archived; it is still active`. Nothing is written.

**Decision 4: read-only.** The command reads `archive.json`, and `goals.json` only to tell an active goal from an unknown one. It writes nothing and takes no lock.

**Decision 5: `aic task history` and `aic task status` are not changed (1B rejected).** They keep reading the active state, and "task not found" keeps meaning that the task is not active.

**Decision 6: no limit and no paging**, as for `aic task history`.

**Rejected inside the decisions:** a second, different format for attempts; matching an id by prefix; merging the archived tasks into `aic task list`; and a flag that prints the raw JSON.

## What this does not do

- It does not restore, edit, search or delete anything in the archive.
- It does not show an archived task through `aic task history` or `aic task status`.
- It does not make the archive tamper-evident.
- It does not limit what it prints. A goal with very many tasks prints all of them.
- It prints what people typed, a reason, a title and a description, as the other commands do.

## Tests the build needs

- A goal that was archived with two tasks and two attempts is shown with its tasks in order, and each attempt has the same lines that `aic task history` printed before the goal was archived. The test archives a goal, and compares the attempt lines with the output of `aic task history` captured before.
- A task with no attempt says `No attempts recorded.` A task with a description shows it, and a task without one does not print an empty line for it.
- A task that was run twice shows two attempts, numbered from 1, oldest first.
- An unknown goal id is refused. An id of a goal that is still active is refused with the message that says so. Spaces around the id are ignored.
- Nothing changes: every state file has the same bytes afterwards, and no archive is created when there is none.
- An archive that cannot be read is an error, and is kept.
- With no argument the command prints the listing as before.
- The shared function gives `aic task history` the same output as before for a task with no attempt, one attempt, a failed attempt, an attempt with no target, a record from before records had a start time, and an attempt that is still open.
- The command is still classified as read-only, and the test that every parser command is classified passes.

## Risks

- **The function that prints an attempt is moved.** `aic task history` has tests, and the move must leave its output the same. This is why the move is the first step, with no change in behaviour.
- **Two commands can now show a history.** A person can ask why `aic task history` says that a task is not found when `aic goal archived` shows it. The error of `aic task history` could say that the task may be archived, and that is a small change that is not part of this note.
- **The output can be long.** A goal with many tasks prints every one.
- **Text from the archive is printed as it is.** A reason or a title can hold anything that a person typed.
- **No Windows observation.** Nothing here was run on Windows.

## Open questions for the maintainer

The maintainer accepted all six recommendations below.

1. **An optional goal id on `aic goal archived`?** Recommended: yes, 1A.
2. **The same lines as `aic task history`, through one shared function?** Recommended: yes.
3. **The id matched exactly, with a separate message for a goal that is still active?** Recommended: yes.
4. **`aic task history` and `aic task status` left as they are?** Recommended: yes.
5. **No JSON export for now?** Recommended: yes.
6. **Should the error of `aic task history` say that the task may be archived?** Recommended: yes, as a separate small change after the view exists, so that a person who has only a task id is told where to look.

## Recommended order

1. **Built.** Move the printing of an attempt out of `aic task history` into one function, with tests that show that its output has not changed.
2. **Built.** The detail view as a library: the text of an archived goal, with tests.
3. **Built.** The optional goal id on `aic goal archived`, with its refusals, and tests through the CLI with the real registries.
4. **Built.** The hint in the error of `aic task history`, if it is accepted.
5. The documentation, and the Windows record.


## Stage 1: built

Stage 1 of the recommended order, one function that makes the lines of an execution attempt, is built, in three commits.

- **The function.** `attempt_lines` in `execution/history.py` returns the lines that show one attempt, the first of them blank, and `aic task history` prints them. The move was meant to change nothing, so tests that pin the exact output of `aic task history` were written and committed first, against the old code.
- **The pinned output.** There are 7 tests of the exact text: a task with no attempts, one completed attempt with a target, two attempts of which one has no target and one has no reason, a record from before records had a start time, an open attempt of a running task, an open attempt of a task that is not running, and an unknown task. They passed on the old code and on the new code, which is what shows that the output did not change.
- **The function's own tests.** There are 8 more, on the lines that the function returns, and one that shows that it prints nothing itself.
- **Found while building.** All 19 mutations of the new function and of its use were caught on the first run.
- **Windows.** The maintainer ran the full suite on Windows under Git Bash before each of the three commits, which gave 1061, 1061 and 1069 passed, each with 2 skipped. The last run was on the tree that became `26176dc`. The tests that pin the output passed there before the move and after it.

## Stage 2: built

Stages 2 to 4 of the recommended order, the text of an archived goal, the goal id on `aic goal archived`, and the hint in the error of `aic task history`, are built, in six commits.

- **The text.** `archived_goal_lines` in `goals/archive_view.py` returns the lines of an archived goal: the goal as the listing shows it and the number of tasks, then each task in the order in which it was archived, with its id, its status, its title, its description when it has one, and either `Attempts: N` or `No attempts recorded.` Each attempt is shown by `attempt_lines`, so the text is the one of `aic task history`.
- **The goal id.** `aic goal archived` takes an optional goal id. Without one it lists the archive, as before. With one it shows that goal. The id is trimmed and matched exactly. A goal that is not archived is refused with `Error: goal <id> is not archived`, and one that is still active with `Error: goal <id> is not archived; it is still active`, both with exit status 1. It writes nothing, and an archive that cannot be read is an error and is kept. The command is still classified as read-only.
- **The hint.** `GoalArchive.find_task_entry` finds the entry that holds a task. When `aic task history` has not found a task among the active tasks, it asks the archive, and if the task is there it adds `The task is in the archive, in goal <id>.` and `Show it with: aic goal archived <id>`. A task that is found never touches the archive, a task that is nowhere gets the same error as before, and an archive that cannot be read gives no hint and leaves the error as it was. `aic task status` is unchanged, as Decision 4 says.
- **Observed on Linux, by hand, with the real CLI and a temporary data directory.** After a goal with two tasks was archived, `aic task history` of one of them printed `Error: task not found`, then the two lines of the hint, and exited 1. An unknown task printed the error alone. `aic goal archived <goal id>` printed the goal, both tasks and both attempts, and exited 0. The text of the attempt of the first task was identical to what `aic task history` had printed before the goal was archived. An id of a goal that was still active printed `is not archived; it is still active`. The checksums of the five state files were the same after the view and the hint.
- **Tests.** There are 22 new tests: 8 for the text, 7 for the command with a goal id and 7 for the hint. One of them runs a task for real and compares the text of its attempt with what `aic task history` printed before the goal was archived.
- **Found while building.** The first mutation run left one of 24 alive: swapping the number of tasks with the number of records in the header could not be seen, because my tests had as many records as tasks. A test with 3 tasks and 1 record was added, and all 24 were then caught. Two of my own tests were wrong and the code was right: one captured the output of another command, and a helper held lines that did nothing.
- **Windows.** The maintainer ran the full suite on Windows under Git Bash after the six commits, which gave 1091 passed and 2 skipped, on the tree that became `d9e646d`. The runs before each commit were not recorded. A run of `aic goal archived <goal id>` or of the hint on Windows by hand was not made then. It was made later, and the record is in [STATUS.md](STATUS.md), in the paragraph that begins `After the Python syntax check the maintainer ran a script on Windows`.
