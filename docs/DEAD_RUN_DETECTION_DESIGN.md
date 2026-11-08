# Design Note: Telling a Dead Run from a Live One

**Status: Accepted as recommended, and built.** This note decides how AIC can know that the process that was running a task has ended, which is what is still open in G5. It follows [STALE_TASKS_DESIGN.md](STALE_TASKS_DESIGN.md), which listed running tasks and said that detection needs an owner or a lease, and [RECOVERY_DESIGN.md](RECOVERY_DESIGN.md), where this was Option B. The evidence was observed on Linux with the real CLI, with one part replaced to make a run slow, and a small script that only prototypes the idea. The evidence below was not run on Windows. The record at the end of this note has the runs on Windows of what was built later.

## Problem

`aic task requeue` puts a `running` task back in the queue. It cannot tell whether the run is really dead. If the run is alive, requeueing and starting the task again runs it twice. `aic task running` shows how long a task has been running, and it says in its output that a listed task may still be running. A person has to decide, and the files give no evidence either way, because a live run and a killed run leave the same records.

When the run is started by `aic task run`, there is a process that owns it: the `aic` process that runs the adapter and then records the outcome. That process is the thing whose end matters. This note asks whether AIC can see that it has ended, and what AIC should do with that.

## Evidence

All of this was run on Linux, with the real CLI and a temporary data directory. The only part that was replaced is the `inspect` adapter: a script made it a `ProcessAdapter` whose child sleeps for 40 seconds, so that a run lasts long enough to be killed. The process adapter, the coordinator, the registries and every command were the real ones.

1. **A hard kill leaves a task that looks like a live one.** While the run was alive, `aic task running` listed the task with `Route: coordinator (inspect)` and `Running for: 3s`. The `aic` process was then killed with `kill -9`. The listing was the same one second later, with `Running for: 4s`. `aic task status` said `running`, and `aic validate` printed `Validation passed.` The child of the adapter was still alive after the kill, as G13 says it can be, since the process adapter starts it in its own session.
2. **`aic task requeue` accepts a live run.** With the run alive, `aic task requeue` printed `Previous status: running`, and the task was `ready`. `aic task start` then accepted the task again while the child of the first run was still alive. Nothing refused or warned.
3. **An operating system lock tells the two cases apart.** A script of a few lines took an exclusive `flock` on a file, which is what `state_lock` does, and started a child with the settings that `ProcessAdapter` uses on POSIX (`start_new_session=True`, the default `close_fds`). From a third process, the lock was `HELD` while the owner was alive. After `kill -9` of the owner it was free. The child was still alive and did not hold the lock. The lock file stayed on disk, empty.

Not observed: any of this on Windows, a hard kill of a run of the real `inspect` or `pysyntax` adapter, and a lock taken by the coordinator, because the coordinator takes none. The script in item 3 is a prototype of the idea and not of the build.

## Facts about the code

- `aic task run` calls `ExecutionCoordinator.coordinate`. The coordinator enters the state guard to start the task, leaves it, runs the adapter, and enters it again to record the outcome. The state lock is never held while an adapter runs (INV-22), so other commands work during a long run.
- The start opens the attempt record before the task moves to `running` (INV-16). `ExecutionStartResult` carries the id of the attempt, `attempt_id`, which is a `uuid4` made when the record is begun.
- `ExecutionRecord` has no field for an owner, and `executions.json` has a schema version that a new field would change.
- `ProcessAdapter` starts its child in its own process group, with `start_new_session=True` on POSIX and `CREATE_NEW_PROCESS_GROUP` on Windows. A hard kill of AIC therefore leaves the child running. This is G13 and it is already documented.
- `locking.py` uses `fcntl.flock` on Unix-like systems and `msvcrt.locking` on Windows. Its module text says that the operating system releases the lock when the process ends, even when it is killed. It keeps a module flag so that one process takes the state lock once.
- `aic task running` is in `cli.READ_ONLY_COMMANDS` and takes no lock. `aic task requeue` takes the state lock for the whole command, like every command that writes.
- `aic task start`, `complete` and `fail` run in a process that ends at once. Work that a person does between them is not run by AIC, so no process of AIC owns it.
- A task that started before execution records existed has no attempt record at all.

## Requirements

1. It is read-only for the report. Finding out whether a run is alive changes no state.
2. It never says that a run is dead when it does not know. A run for which nothing is known is `unknown`, which is what every run is today.
3. No new field in any state file, and no schema change.
4. It fits the lock model. The state lock is still never held while an adapter runs, and nothing waits on a long lock.
5. It does not depend on a clock, because the project already reports time problems and refuses nothing for them.
6. It does not make a decision for a person. AIC reports and refuses an action that is plainly wrong, and it does not requeue anything by itself.
7. A crash of any step leaves a state that the existing commands still handle.

## Options

### Decision 1: how to know that the owner has ended

**1A. An operating system lock for each attempt, held by the process that runs it (recommended).** The `aic` process that runs an attempt takes an exclusive lock on a small file whose name holds the id of the attempt, and keeps it while the adapter runs and until the outcome is recorded. Another process asks by trying to take the same lock without waiting. A lock that cannot be taken means the owner is alive. A lock that can be taken, on a file that exists, means that the owner ended. The operating system releases the lock when the process ends, even when it is killed (evidence 3).

- Pro: no process id, no clock and no heartbeat. Nothing is written during the run, so the state lock is not touched. No state file changes.
- Con: one small file for each run, and the behaviour on Windows is not observed. It is the same kind of lock as the state lock, so it shares its limits, and it is not reliable on network file systems.

**1B. Record the process id of the owner, and its start time, in the attempt.** A process id can be reused, and a start time needs a call that the standard library does not give on Windows. It means nothing on another host. It is a new field in `executions.json`, so a schema bump and a migration. Rejected.

**1C. A lease with a heartbeat.** The owner would write a time into a file every few seconds, and a reader would call the run dead when the time is old. The number of seconds is a guess of the kind G13 already lists, a clock that moves back breaks it, and the writer has to write during the adapter. It needs the state lock, which breaks INV-22, or a second file, which is what 1A is without the guess. Rejected.

**1D. Let the child hold the lock, so that the lock means that the work is alive.** It would answer the better question, which is whether the work has stopped. It needs the child to inherit a descriptor on POSIX, which Python closes in a child by default (evidence 3 relied on that), and `msvcrt` locks are not inherited at all. The child also starts in its own session so that it can be stopped as a group. Rejected for now. The cost is that `gone` means that the process of AIC ended, and that its child may still be running (see Decision 4).

**1E. Do nothing.** A person keeps deciding with no evidence, and requeueing a live run stays possible. Not recommended.

### Decision 2: where the lock is, and when it is held

**2A. A file `<id of the attempt>.lock` in a directory `runs` of the data directory, taken by the coordinator right after the start succeeded and released after the outcome is recorded (recommended).** The file is empty and is never read. The coordinator takes it after it left the state guard, because the id of the attempt is known only then. For a short moment a task is `running` with no lock file, and a reader that finds no file answers `unknown`, so the moment cannot produce a wrong answer. A crash in that moment leaves `unknown`, which is today's state.

**2B. Take the lock before the start, so that it exists from the first moment.** The id of the attempt does not exist yet, so the file would have to be named after the task. A file that outlives a crash would then belong to an older attempt of the same task, and a reader could call a manual run dead because of it. Naming the file after the attempt avoids this. Rejected.

**2C. One lock file for all runs.** It says that some run is alive, and not which. Rejected.

### Decision 3: what the reader does

**3A. Read the record, try the lock, then read the record again (recommended).** The reader finds the open attempt of the running task, opens the lock file without creating it, and tries to take the lock without waiting. If it fails, the owner is `alive`. If it succeeds, the reader reads the task and the attempt again. If the attempt is still open and the task is still `running`, the owner is `gone`. If not, the run ended while the reader looked, and the answer is that it ended and not that it died. The owner closes the attempt before it releases the lock, so a lock that can be taken, followed by an attempt that is still open, is proof.

**3B. Try the lock without reading again.** A run that ends normally between the read and the lock would be called dead. Rejected.

The reader never creates the file. The owner may try to take the lock while a reader holds it for an instant, so the owner retries for a short time, as `state_lock` does, before it gives up.

### Decision 4: what is reported

**4A. A line `Owner:` for each task in `aic task running` (recommended).** It says `alive`, or `gone`, or `unknown`, each with its meaning: `alive (the aic process that runs it holds its lock)`, `gone (the aic process that ran it has ended; its child may still be running)` and `unknown (no lock was recorded for this run)`. `gone` is not `dead work`, because of G13, and the line says so. The exit status stays 0, as in the earlier note.

**4B. Say `dead` and `stale`.** The files and the lock cannot show that the work stopped. Rejected, as the earlier note rejected the names.

### Decision 5: what `aic task requeue` does

**5A. Refuse a task whose owner is `alive` (recommended).** `Error: the run of task <id> is still alive: the aic process that runs it holds its lock. Wait for it to end, or stop that process, and then requeue.` There is no option to override it. It closes the half of G5 that says that a live run can be requeued and run twice, for runs that AIC owns. For `gone` and `unknown` the command works as it does today. For `gone` it adds one line, that the child of the run may still be running.

- Pro: the refusal rests on a positive fact, a process that holds a lock. A refused person has a way out: a run ends by itself within the time limit of its adapter, 60 seconds by default, or the process is stopped and the lock goes with it.
- Con: if a lock is held by something that is not an `aic` run, such as a file system that fakes locks, a task cannot be requeued through the CLI. The state lock has the same weakness.

**5B. Warn and go on.** It leaves the double run possible, and a warning is easy to miss. Rejected.

**5C. Refuse, with an override option.** It reopens the case that the refusal closes, and the first person to be in a hurry will use it. Rejected for now.

### Decision 6: whether AIC acts on `gone`

**6A. No. It reports, and the person requeues (recommended).** AIC owns state and permissions, and a person stays in control. A run that is `gone` may have left a child that still works, and the adapters that exist read only, but the adapters that come later may not.

**6B. A command that requeues every task whose owner is `gone`.** It is small, and it is the step after this one. It should wait until a real use shows that it is wanted, and until the Windows behaviour is known. Not now.

### Decision 7: the other commands

**7A. Nothing else changes (recommended).** `aic validate` does not report it, for the reason of the earlier note: a run that ended without an outcome is not invalid state. `aic task start`, `complete` and `fail` are not changed. A task started with `aic task start` has no owner, and its `Owner:` line says `unknown`, which is true, because a person does the work.

**7B. Refuse `aic task complete` for a run that is `alive`.** The attempt identity already refuses the outcome of a superseded attempt. Not now.

### Decision 8: the files

**8A. The files are removed by the owner at a normal end, and by `aic task requeue` for the run that it recovers (recommended).** A file that is left by a killed run is empty, and it is harmless. It is never read except to test the lock. Nothing else removes it. `aic validate` does not look at the directory.

**8B. A command that cleans the directory.** More surface for little. Not now.

## Recommendation

Take 1A, 2A, 3A, 4A, 5A, 6A, 7A and 8A, in this order of work.

1. A small module that holds a lock for an attempt and that probes one, so that it can be tested alone.
2. The coordinator takes the lock after the start and releases it after the outcome is recorded, also when the adapter raises and when the recording fails. If the lock cannot be taken, for example because the directory cannot be made, the run goes on without an owner, which is today's behaviour, and the result says so in one line.
3. `aic task running` shows `Owner:`.
4. `aic task requeue` refuses an `alive` owner and removes the file of the run that it recovers.

No state file changes, no schema bump, and no new command. One directory appears in the data directory, and it is created by the first run.

## What this does not do

- It does not detect a dead run that a person started with `aic task start`. Nothing owns such a run.
- It does not stop a child that is still running after AIC was killed (G13), and it says so when the owner is `gone`.
- It does not requeue anything by itself.
- It does not cover a run that started before this exists. Its owner is `unknown`.
- It does not protect against a process of the same user that takes the lock on purpose, or against a person who edits `tasks.json`. The lock is advisory, as the state lock is.
- It does not work across machines, and it is not reliable on network file systems.
- It does not close the false success that `aic task complete` can record for a dead task.

## Tests the build needs

- A lock for an attempt is held by one holder, a probe of it fails while it is held and succeeds after it is released, and a probe of a file that does not exist answers `unknown` and creates nothing.
- A real process that holds a lock and is killed leaves a lock that a probe can take. It runs in a thread with a join timeout, and it checks nothing on Windows until a Windows run shows that it does.
- The coordinator holds the lock while the adapter runs, so a probe from inside a fake adapter finds it held, and it releases the lock after the outcome is recorded, after an adapter that raises, and after a recording that fails.
- A lock that cannot be taken does not stop the run, and the result says that no owner was recorded.
- `aic task running` prints `alive`, `gone` and `unknown` for the three states, and a task that finished while the reader looked is not called `gone`.
- `aic task requeue` refuses an `alive` run with the message, writes nothing, and works for `gone` and for `unknown`, where `gone` adds its line. It removes the file of the run that it recovers.
- The classification does not change: `aic task running` takes no lock and is read-only, and `aic task requeue` locks.
- No state file changes its content or its schema version.
- Mutations: the probe without the second read, the lock released before the outcome is recorded, the lock taken before the attempt exists, the refusal skipped, the refusal for `gone`, and a missing file answered as `gone`, are each caught.

## Risks

- **Windows.** `msvcrt.locking` is a lock on a range of bytes. That the lock is released when a process is killed, how soon, that a file that was locked can be removed after it is closed, and that a locked range cannot be read, were not observed. The lock file is never read, but a probe opens it. A run of the module on Windows has to come before the coordinator uses it.
- **A lock held for the length of a run.** It is held by a process that is alive, so it ends with the run, and a run is limited to 60 seconds by default. An adapter with no time limit would hold it for as long as it runs, and this is the meaning of `alive`.
- **A false `alive`.** A file system that grants locks that it does not keep would block a requeue. The state lock has the same dependence.
- **A false `gone`.** It needs a lock file that exists, that can be taken, and an attempt that is still open after the lock was taken. The owner closes the attempt before it releases the lock, so a normal end cannot produce it. A crash between closing the attempt and releasing the lock is also a normal end, and the attempt is closed.
- **Files left behind.** A killed run leaves an empty file in `runs`, and they add up only as fast as runs are killed.
- **`gone` can be read as `stopped`.** The line says that the child may still be running, and G13 stays open.

## Open questions for the maintainer

Each has a recommendation, and the reply "continue with best" accepts them all.

1. Use an operating system lock for each attempt for runs that `aic task run` starts (1A)? Recommendation: yes.
2. Make `aic task requeue` refuse a run that is `alive`, with no override (5A)? Recommendation: yes.
3. Only report, and never requeue by itself (6A)? Recommendation: yes.
4. When the lock cannot be taken, let the run go on with no owner and say so (Recommendation 2)? Recommendation: yes, because the result of the run does not depend on it.
5. Keep the files in a directory `runs`, and remove them only at a normal end and in `aic task requeue` (8A)? Recommendation: yes.
6. Leave `aic validate` and the other commands as they are (7A)? Recommendation: yes.
7. Build the module and run it on Windows before the coordinator uses it? Recommendation: yes.

## Recommended order

1. Add the module that holds and probes a lock for an attempt, with its tests. Built.
2. Run a script on Windows that holds the lock in one process, kills it, and probes from another, with the maintainer, before anything uses the module. Done, and the record is at the end of this note.
3. Let the coordinator take the lock, with its tests. Built.
4. Show `Owner:` in `aic task running`, with its tests. Built.
5. Refuse `alive` in `aic task requeue` and remove the file, with its tests. Built.
6. Write the documentation, with the Windows record after the maintainer runs it, and update G5 in STATUS. Done, and the record is at the end of this note.

## What was built so far

The seven open questions were not answered. The build went ahead on the assumption that the recommendations were accepted, as it did for the earlier notes, and the maintainer did not object. Steps 1 and 2 of the recommended order are done. Steps 3 to 6 are not.

- **The module.** `execution/run_lock.py`, in the commit `41b6fae`. It has `hold_run_lock`, `probe_run_lock`, `run_lock_path`, `RunLockError` and the three answers `alive`, `gone` and `unknown`, and it reuses the lock and unlock calls of the state lock. It has one rule that this note did not state. An attempt ID that is not made of ASCII letters, digits, hyphens and underscores, up to 100 characters, is refused, because an ID in a record that a person edited by hand could name a path outside `runs`. A probe of such an ID answers `unknown`.
- **The tests.** 34 tests in `tests/unit/test_run_lock.py`, in the commit `9278e6f`. Two of them use a real process that holds the lock. One kills it, and one lets it end normally. Both return early on Windows, where nothing is checked by them.
- **What does not change.** Nothing calls the module. The coordinator, `aic task running` and `aic task requeue` are as they were, and no command behaves differently.

### What was run

- **Mutations.** Fourteen mutations of the module were run, and 13 were caught. The first run showed a gap, because nothing tested that a missing data directory is made, and a test was added before the final run. The survivor moves the removal of the file before the closing of its handle. It changes nothing on Linux, where an open file can be removed. On Windows an open file cannot be removed, as the run below shows, so the suite there should catch it, but the mutation was not run on Windows.
- **The suite on Windows.** The maintainer ran it under Git Bash before each of the two commits, which gave 1212 and 1246 passed, each with 2 skipped. The last run was on the tree that became `9278e6f`.
- **A script on Windows.** It runs real processes in a temporary directory, with Python 3.14.3 on Windows. Twelve checks had an expected answer, and all came out as expected. Three were observations only.
  - A lock that another process holds is `alive`.
  - After that owner was killed with `Popen.kill`, which ends a process at once on Windows, the lock was `gone` at the first probe. The loop would have waited up to 5 seconds, and it measured 0 milliseconds, in one run.
  - The child of the owner, started with the same process group flags as the process adapter, kept running after its owner was killed.
  - The file that the killed owner left could be removed.
  - An owner that ended normally left no file, and its attempt then probed as `unknown`.
  - A probe from the process that holds the lock answered `alive`, so a second handle in one process conflicts with the first, which is how the tests use it.
  - Two probes of a file that nobody holds both answered `gone`, and the lock could be taken afterwards, so a probe does not keep it.
  - Observation: a second try to take a held lock fails with `PermissionError` and errno 13. It is an `OSError`, which is what the module catches.
  - Observation: removing the file while its owner holds it is refused with `PermissionError`. On Linux the same removal succeeds. The owner must therefore close its handle before it removes the file, and the module does.

### What this changes in the note

The first risk of the note, Windows, is answered for the maintainer's machine for the module: the lock is released when its owner is killed, a closed file can be removed, and a second handle conflicts with the first. A failed lock is a `PermissionError`, so a probe that finds the lock held cannot be confused with an error that is not an `OSError`. The rest of the note stands as it was written.

### Not known

- Only one machine was used, with Windows 11 and Python 3.14.3. Python 3.11 was not tried.
- How soon the lock is released after a kill was seen once, as 0 milliseconds. A slower release would show as `alive` for a moment, which is the safe side for a refusal in `aic task requeue`.
- A hard kill of a run of the real `inspect` or `pysyntax` adapter on Windows was not made then, because the coordinator did not take the lock yet. A hard kill of a real run with the `inspect` adapter was made later, as the last section records.
- A network file system was not tried, and the module shares the limits of the state lock there.

## What was built in steps 3 to 5

Steps 3 to 5 followed the recommendation of this note, and the maintainer did not object. All six steps of the recommended order are now done.

- **Step 3, the coordinator.** The code is in the commits `d8fd37b` and `05ed79a`, and its tests are in `8f00847` and `f5c04d9`. `ExecutionCoordinator` takes an optional `run_guard`, a function that gets the ID of an attempt and returns a context manager. After the start succeeded, the coordinator enters the guard, outside the state guard, and leaves it after the outcome is recorded, so the attempt is closed before the lock is released. It also leaves it when the adapter raises, when the adapter returns something that is not an outcome for the task, and when the recording fails. A start that reports no attempt ID takes no lock. If the guard cannot be entered, the adapter runs anyway, and the result carries a `note` that says in one line that no owner was recorded and why. The reason that is stored in the attempt is not changed. `aic task run` passes a guard that holds the run lock in the data directory, and it prints the note as `Note:`.
- **Step 4, the report.** The code is in `5e3c4e3` and `98204a2`, and its tests are in `fc2f693` and `a1177f4`. `describe_running_tasks` takes an optional data directory, and each row has an `owner`. For a task with an open attempt, the report probes the lock, and it reads the attempt again only when the lock is free. `aic task running` prints an `Owner:` line after `Running for:`. The command still takes no lock, writes nothing and creates no directory. Without a data directory every owner is `unknown`.
- **Step 5, the requeue.** The code is in `0a16dd0` and `43f6483`, and its tests are in `8f856a8` and `9142a29`. `aic task requeue` asks for the owner after it has checked the status and the parent goal. A run whose owner is alive is refused with `Error: the run of task <id> is still alive: the aic process that runs it holds its lock. Wait for it to end, or stop that process, and then requeue.`, with exit status 1 and nothing written. When the owner is gone, the task is requeued as before, the lock file of the attempt is removed, and a note says that the child of the run may still be running. When the owner is unknown, the command is as it was. The footer of `aic task running` has one more line, that the command refuses a run whose owner is alive. The check that the report uses was renamed `owner_of_attempt` so that the command can share it, and `remove_run_lock_file` was added to the module of the lock.

### What differs from the note

- The report has a fourth answer, `ended`, with the text `ended (the run ended while this was checked)`. The note described the case, a run that was closed or replaced between the probe and the second read, and gave it no text.
- `ExecutionCoordinateResult` has a new field, `note`, to carry the line that the note asked the result to say.
- One existing test was changed, in its own commit before the code. `test_requeue_works_while_the_adapter_runs` requeued a run while its adapter ran, which the refusal now forbids, and it failed against the new code with `requeued == [1]`. It became `test_requeue_works_while_the_adapter_of_a_run_with_no_owner_runs`: the run lock cannot be made in it, so nobody vouches for the run and the requeue is allowed, and the path of a superseded outcome through the CLI is still covered.
- No decision of the note changed. No state file, format or schema version changed, and no new command was added.

### What was run

- **Tests.** 66 tests in six files, which are `test_coordinator_run_lock.py` (18), `test_task_run_lock.py` (7), `test_running_owner.py` (15), `test_task_running_owner.py` (8), `test_run_lock_remove.py` (5) and `test_task_requeue_owner.py` (13). The suite on Linux has 1314 tests.
- **Tests against the old behaviour.** Without the wiring in `aic task run`, 6 of the 7 CLI tests of step 3 failed, and with a coordinator that ignores its guard, 12 of the 17 tests that existed then failed. Without the change in `aic task running`, 7 of the 8 CLI tests of step 4 failed. Without the refusal, 6 of the 13 tests of step 5 failed. The tests that passed are those for cases that the new code does not change.
- **Mutations.** Fourteen mutations of the coordinator and the command in step 3, fifteen of the report and the command in step 4, and fourteen in step 5 were run, and all were caught on Linux. The first run of step 3 left one survivor, the check that a start has an attempt ID, and a test was added. None were run on Windows.
- **Output compared before and after.** The output of 7 commands, a completed run, a refused one, an unknown target, a repeat run, history, targets and validate, was identical with and without step 3. The output of `aic task running` with and without `--older-than` was identical apart from the `Owner:` lines. The output of 7 requeue-related commands was identical for every case that has no lock file.
- **The real CLI on Linux.** A real `aic task run` was made with the `inspect` adapter replaced by a slow stand-in, in each of the three steps. The run created `runs/<attempt id>.lock` and probed `alive`. After `kill -9` of the `aic` process it probed `gone`, the task stayed `running`, and the child was still alive. `aic task running` showed `Owner: alive` and then `Owner: gone`, and a task that a person started with `aic task start` showed `Owner: unknown` throughout. `aic task requeue` refused the live run and left it as it was, and after the kill it requeued the task, removed the lock file and printed the note.
- **The suite on Windows.** The maintainer ran it under Git Bash before each of the four commits of block CM, which gave 1246, 1264, 1264 and 1271 passed, and before each of the four commits of the report, which gave 1271, 1286, 1286 and 1294 passed, each with 2 skipped. The last run of each block was on the tree that became `f5c04d9` and `a1177f4`, in that order. The tests that kill a real owner process, in `test_task_running_owner.py` and `test_task_requeue_owner.py`, are not skipped on Windows, and they ran in the suite of `a1177f4` and in the one of `9142a29`.
- **Block of step 5 on Windows.** The maintainer ran that block and pushed it, and its output was not seen. A read-only check on Windows afterwards showed that the six commits were in order, that `HEAD` was the same as `origin/main`, that all six files were equal to the verified run, and that the suite gave 1312 passed, with 2 skipped, on the commit `9142a29`. The counts before each earlier commit of that block were not seen.

### Not known

- A hard kill of a real run through `aic task run` on Windows was not made when steps 3 to 5 were recorded, and was made later, as the last section records. The runs on Linux used a slow stand-in for the adapter, and the Windows evidence then was the script of step 2 and the tests above.
- A run that a person starts with `aic task start` has no owner, and its owner is always `unknown`. Nothing detects that it died.
- `gone` means that the process of `aic` ended. The child of a process adapter can still be running (G13), and requeueing then starts the task again beside it. The adapters that exist read only.
- Any `OSError` on taking the lock counts as held, as it does for the state lock. On Windows a held lock was seen as `PermissionError` with errno 13, and a different error would also read as `alive`, which is the safe side for a refusal.
- How soon the lock is released after a kill on Windows was seen once, as 0 milliseconds.
- A network file system was not tried, and the run lock shares the limits of the state lock there.
- A race between a probe and the end of a run in `aic task requeue` was not tested. The command holds the state lock, and a run needs it to record its outcome, so the outcome cannot be recorded while the command looks.

## A hard kill of a real run on Windows

After steps 3 to 5 the maintainer ran a script on Windows under Git Bash, with Python 3.14.3, that makes two cases through the real CLI in temporary data directories. The first case is a hard kill. The script runs the real `aic task run --target inspect` on the folder of the Python standard library, which the run only reads, and kills the `aic` process with `Popen.kill`, which ends a process at once on Windows. All 18 checks of this case that had an expected answer came out as expected.

- The lock file appeared while the run was going, and the run was still going after a delay of 0.5 seconds.
- `aic task running` showed `Owner: alive`. `aic task requeue` was refused with exit status 1 and the message that the run is still alive, and the task stayed `running`.
- After the kill, the `aic` process had ended with a status that is not zero. `aic task running` showed `Owner: gone` at 0.3 seconds after the kill, the task was still `running`, and one lock file was left.
- `aic task requeue` then succeeded with exit status 0 and the note that the child may still be running. The task was `ready`, and no lock file was left.

The script did not look at the child of the adapter, so what a hard kill does to the child of the real `inspect` adapter on Windows was not observed. The 0.3 seconds is the time at which a poll saw `gone`, and a poll starts a new `aic` process, so the lock may have been released sooner. The case was run once, on one machine.

The second case of the script is the one of [GOAL_ARCHIVE_LATE_TASK_DESIGN.md](GOAL_ARCHIVE_LATE_TASK_DESIGN.md), and its record is in that note.
