# Design Note: A Limit for the Project Snapshot

**Status: Proposed. Not accepted.** This note reopens one question that [FIRST_ADAPTER_DESIGN.md](FIRST_ADAPTER_DESIGN.md) decided: whether a project above some size may be run by an adapter that is wrapped in a read-only check. That note chose to leave it unlimited at first, because any number then would have been a guess. Measurements on Windows since then show what an unlimited snapshot costs. Nothing in this note is built.

## Problem

`ReadOnlyAdapter` takes a snapshot of the project before a run and another after it. A snapshot opens every file below the project directory and hashes it. Nothing limits how many files there are or how large they are, and the 60 second timeout of the process adapter covers only the child, not the two snapshots. A person who registers a large directory as a project, which includes a Python project that holds its own virtual environment, waits for the snapshots with the task `running` and the run lock held, and nothing says why. Interrupting the command leaves the task `running`.

A late refusal is worse than the wait. The reason is in Evidence 5: a task that ends `failed` fails its goal, and a failed goal accepts no new task. So the limit has to refuse a run before it starts.

## Evidence

All numbers marked Windows were observed by the maintainer under Git Bash with Python 3.14.3. Each was run on a project directory that was only read.

1. **How long the first child took to appear.** In five trials of `aic task run --target inspect` on the folder of the Python standard library, the first child of the `aic` process appeared 77.86, 36.18, 37.74, 34.10 and 46.29 seconds after the start. By the code the first snapshot is taken before the child starts. This is recorded in [DEAD_RUN_DETECTION_DESIGN.md](DEAD_RUN_DETECTION_DESIGN.md).
2. **What was in that folder.** A script that only reads timed `take_snapshot` on it. The folder was `Lib` of the installed Python. It had 58,279 files, 1,602.0 MiB and 5,841 directories, and 55,392 of the files were below `site-packages`. Of the files, 31,807 were under 4 KiB, 23,522 were from 4 KiB to 64 KiB, 2,821 from 64 KiB to 1 MiB, and 129 were 1 MiB or more, which together held 753.2 MiB. The snapshot had 64,120 entries, which is what a separate walk counted.
3. **Where the time went.**

   | Step | AIC repository (control) | `Lib` |
   | --- | --- | --- |
   | Files, MiB | 3,618 files, 10.9 MiB | 58,279 files, 1,602.0 MiB |
   | Walk with no file read | 0.14 s | 0.87 s |
   | Opening every file, first pass | 1.38 s (0.38 ms per file) | 92.92 s (1.59 ms per file) |
   | Reading and hashing, first pass | 1.44 s | 32.14 s |
   | `take_snapshot`, runs 1, 2 and 3 | 1.76, 1.76, 1.78 s | 47.00 and 47.80 s |

   The walk is cheap and the reading is not. A run takes two snapshots, so a run on `Lib` spends about 94 seconds in them. The first pass over the files, which came first in the script, took about 125 seconds, against 47 seconds for each snapshot after it. In evidence 1 the first trial took 77.86 seconds and the others 34 to 46. So a cold read is slower than a warm one. The cause was not observed, and antivirus scanning of files that are opened for the first time is one possibility that was not tested.
4. **What the earlier measurement said.** [FIRST_ADAPTER_DESIGN.md](FIRST_ADAPTER_DESIGN.md) recorded 0.616 seconds to read and hash the AIC repository, then 2,175 files and 5.0 MiB. That did not predict the cost of a large tree: the same repository now has 3,618 files (3,253 of them below `.git`) and takes 1.76 seconds.
5. **A failed task fails its goal.** On Linux with the real CLI, a goal with two tasks had its first task started and then failed with `aic task fail`. `aic goal status` then showed the goal as `failed`, `aic task ready` for the second task gave `task cannot be marked ready: parent goal is failed`, and `aic task create` for the goal gave `Cannot create task for failed goal`.
6. **Stat data is not enough to prove a file unchanged.** [FIRST_ADAPTER_DESIGN.md](FIRST_ADAPTER_DESIGN.md) recorded that twenty same-size rewrites of a file, each made straight after the last, changed its modification time only five times on Windows. That is why a snapshot hashes.
7. **Linux.** A folder of 1,212 files and 50.8 MiB took 0.05 seconds to snapshot in a Linux sandbox. The limits below rest on the Windows numbers only.

**Not known.** Whether antivirus is the cause of the slow first read. How a network file system behaves. How large real projects are: the only large directory that was measured was `Lib`. What a snapshot costs on macOS, on Python 3.11, or on a slow disk.

## Facts about the code

- `take_snapshot` in `execution/snapshot.py` walks with `os.scandir`, reads the status of each name without following links, and opens and hashes every regular file. It has no limit. An unreadable name is recorded as unreadable.
- `ReadOnlyAdapter.execute` in `execution/readonly.py` takes the first snapshot, runs the adapter, takes the second, and compares. An `OSError` from either snapshot gives a failed outcome. Its docstring says that the snapshots are not limited in time or in the number of files.
- The process adapter has the timeout of 60 seconds and an output cap. It is inside the wrapper, so the snapshots are not covered.
- The coordinator copies `requires_grant` and `requires_project` from the adapter into the request, and then calls the starter inside the state guard. The starter runs admission first. A refusal there returns a rejected result, leaves the task `ready` and writes nothing. Admission checks readiness, then the project directory, then the grant.
- The state lock waits at most 10 seconds for another command (`DEFAULT_LOCK_TIMEOUT`). Admission runs while the lock is held.
- `aic task run` handles `KeyboardInterrupt` by printing `Interrupted.` and returning 130. The task stays `running`, and the message says to use `aic task complete`, `fail` or `requeue`.
- `inspect` and `pysyntax` are wrapped in `ReadOnlyAdapter`. `noop` is not, and needs no project.
- `pysyntax` has its own limits for the files that it reads: 1 MiB per file, 10,000 files and 64 MiB. They are guesses (G24).

## Requirements

1. A run that would spend a long time in snapshots is refused before it starts, with a reason that says why and what to do.
2. A refusal writes nothing and leaves the task `ready`, so that the goal does not fail for a refusal that is only policy.
3. The limit is a count, so that it behaves the same on every platform and can be tested without a slow machine.
4. Checking the limit costs much less than the snapshot, and its cost is bounded.
5. A project within the limit gets the same guarantee as now: every file is hashed, twice.
6. An adapter that takes no snapshot is not affected.

## Options

- **A. Leave it unlimited and report the time.** This is what [FIRST_ADAPTER_DESIGN.md](FIRST_ADAPTER_DESIGN.md) chose. Rejected. A report after the wait does not stop it, and the report was not built.
- **B. A time limit on the snapshots.** Rejected as the main control. The time depends on the machine and on whether the files are cached (evidence 3), so the same project would be accepted on one run and refused on the next. It would also fail the run after the start, which fails the goal (evidence 5). It stays as an open question, as a backstop.
- **C. A limit on the number of files and their total size, checked by a survey that reads no file.** Recommended. The walk costs 0.87 seconds for 58,279 files, and the survey stops as soon as a limit is passed, so its cost is bounded by the limit.
- **D. The same limit inside `ReadOnlyAdapter.execute` only.** Rejected as the place of the refusal, because it comes after the start and would fail the goal. A bound inside the wrapper is still needed for a project that grows between admission and the run.
- **E. Leave out directories such as `.git`, `.venv` or `node_modules`.** Rejected in this change. It would silently weaken the read-only guarantee for those directories. It may come later as an explicit setting of the project, as open question 3 says.
- **F. Compare only size and modification time, and hash less.** Rejected. Evidence 6 shows that it can miss a rewrite.
- **G. Hash and open files in several threads.** Rejected for now. It might make a snapshot faster, and it bounds nothing.
- **H. Snapshot a sample of the files.** Rejected. A sample cannot show that the rest was unchanged.

## Recommendation

1. **Two limits.** A project may have at most 20,000 regular files and 256 MiB in regular files, as constants in code. Directories and links do not count as files. They are guesses, and the reasoning for them is below.
2. **A survey.** `survey_project(root, max_files, max_bytes)` in `execution/snapshot.py` walks as `take_snapshot` does, with no link followed, and reads only the status of each name. It stops as soon as one limit is passed, and returns the counts, which limit was passed, and the top-level folders with the most files among those counted.
3. **The refusal is in admission.** The request gets a new field, `snapshots`, which is false by default. The coordinator sets it from an attribute of the adapter, and `ReadOnlyAdapter` sets it true. Admission runs the survey after the directory check and after the grant check, so the cheap refusals come first. A project over a limit is refused with a reason that gives the limit, says that the count is until the limit was passed, names the folders with the most files, and says that a read-only run reads every file twice. A refusal leaves the task `ready`, writes no record and takes no run lock.
4. **A bound in the snapshot itself.** `take_snapshot` takes optional limits and raises an `OSError` that says which limit was passed. `ReadOnlyAdapter` passes the limits, so a project that grew since admission, or a run that added a great many files, ends as a failed outcome with a reason and not as a long wait.
5. **No exclusions, no setting and no time limit in this change.** They are open questions 2 to 4.
6. **The idea of reporting the time is dropped.** [FIRST_ADAPTER_DESIGN.md](FIRST_ADAPTER_DESIGN.md) question 7 recommended it, and it was never built. This note replaces it with the limit.
7. **Where the numbers come from.** A fit of the two Windows points in evidence 3, with the time of one snapshot as a number of seconds per file plus a number per MiB, gives about 0.45 ms per file and 13 ms per MiB. This is arithmetic on two points and not a measurement. At 20,000 files and 256 MiB it gives about 12 seconds for a snapshot, and about 25 seconds for the two snapshots of a run, on a warm cache. The cold read in evidence 3 was about 2.7 times slower, so a cold run could take about a minute. The AIC repository, at 3,618 files and 10.9 MiB, is well within the limits, and `Lib` is far above them.

## What it does not do

- It does not make a snapshot faster.
- It does not bound the time of a project that is within the limits, on a slow disk or with a cold cache.
- It does not help a Python project that holds a virtual environment beyond telling the person why the run was refused and which folders hold the files.
- It does not change grants, the read-only check, the process adapter or `noop`.
- It adds no setting.

## Tests the build needs

- **The survey.** Exactly at a limit is accepted and one past it is refused, for the files and for the bytes, with small limits passed as arguments. It stops early, which a fake `os.scandir` that counts its calls shows. A link is not followed. An unreadable directory is skipped. The top folders are the ones with the most files, with a fixed order for ties, and at most a few are returned.
- **The snapshot.** With limits, `take_snapshot` raises when a limit is passed, and without limits it is unchanged.
- **Admission.** A request with `snapshots` set is refused over a limit and accepted at it. It is not surveyed when `snapshots` is false. A missing directory and a missing grant are refused first, and the survey does not run for them.
- **The coordinator and the starter.** A refused run leaves the task `ready`, writes no execution record, creates no `runs/` folder, and leaves the goal status as it was.
- **The CLI.** Through `main()` with real registries and small limits: `aic task run --target inspect` and `--target pysyntax` are refused with the reason, with exit status 1, and the task is `ready`. `--target noop` is unaffected. A project within the limits runs as before.
- **The race.** A fake snapshot that exceeds the limit during the run gives a failed outcome with the reason.
- **Mutations.** Each limit off by one, the early stop removed, the order of the checks, and the survey run for an adapter that takes no snapshot.
- **On Windows.** A step that runs `aic task run --target inspect` on `Lib` is expected to be refused in a short time, with the task still `ready`, and one on a project below the limits is expected to run.

## Risks

- The numbers are guesses from two Windows points and one repository, and they can refuse a project that a person expected to run.
- The survey runs while the state lock is held, for at most the walk of 20,000 files. At the measured cost that is about 0.3 seconds, and on a slow or network file system it could be far longer. Other commands wait 10 seconds for the lock.
- The folder counts in the reason are partial, because the survey stops at the limit.
- A project with a virtual environment inside it is refused, and there is no way around that until an exclusion exists. That may be common.
- A cold cache makes a project that is within the limits slower than the estimate.

## Open questions

1. **What should the limits be?** Recommendation: 20,000 files and 256 MiB, as above, and review them when a real project is refused or is slow.
2. **Constants or a setting?** Recommendation: constants first. A setting is a new surface, and the numbers are guesses that should be changed with evidence.
3. **Should some directories be left out of the snapshot?** Recommendation: not in this change. Design it separately, as an explicit setting of the project, that is recorded in the outcome so that the weaker guarantee is visible.
4. **Should there also be a time limit?** Recommendation: no. With the count limits the cost is bounded, and a time limit would fail runs after the start.
5. **Should the survey run inside the state lock or outside it?** Recommendation: inside, in admission, because the project path is found there and the walk is bounded by the limit. Revisit it if the lock times out on a slow file system.
6. **Should `.git` count?** Recommendation: yes, with everything else. It held 3,253 of the 3,618 files of the control repository, and a read-only adapter should not change it either.
7. **Should the limits be shown by `aic task targets`?** Recommendation: no. The refusal gives them when they matter.

## Recommended order

1. Add `survey_project` and its tests.
2. Add the limits to `take_snapshot`, and `ReadOnlyAdapter` passing them, with their tests.
3. Add the `snapshots` field and the check in admission, with their tests. Pin the messages of the admission refusals that exist before the new one is added.
4. Set the field from the adapter in the coordinator, and add the tests of the refusal through the starter, the coordinator and the CLI.
5. Write the documentation, with the Windows record after the maintainer runs the step, and change G16 in STATUS.
