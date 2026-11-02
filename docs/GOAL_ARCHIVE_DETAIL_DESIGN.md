# Design Note: Reading the History of an Archived Goal

**Status: Proposed. Not accepted, and no code is written.** It extends [GOAL_ARCHIVE_DESIGN.md](GOAL_ARCHIVE_DESIGN.md), whose three stages are built. Everything below the evidence is a recommendation for the maintainer to accept, change or reject. Nothing in it was run on Windows.

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

1. **An optional goal id on `aic goal archived`?** Recommended: yes, 1A.
2. **The same lines as `aic task history`, through one shared function?** Recommended: yes.
3. **The id matched exactly, with a separate message for a goal that is still active?** Recommended: yes.
4. **`aic task history` and `aic task status` left as they are?** Recommended: yes.
5. **No JSON export for now?** Recommended: yes.
6. **Should the error of `aic task history` say that the task may be archived?** Recommended: yes, as a separate small change after the view exists, so that a person who has only a task id is told where to look.

## Recommended order

1. Move the printing of an attempt out of `aic task history` into one function, with tests that show that its output has not changed.
2. The detail view as a library: the text of an archived goal, with tests.
3. The optional goal id on `aic goal archived`, with its refusals, and tests through the CLI with the real registries.
4. The hint in the error of `aic task history`, if it is accepted.
5. The documentation, and the Windows record.
