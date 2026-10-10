# Design Note: File Locking

**Status: Proposed.** Nothing in this note is implemented. It needs the maintainer's approval, or changes, before any code is written. It addresses the file locking half of gap G4 in [STATUS.md](STATUS.md). The other half of G4, a history of status changes, is a separate decision.

## Problem

Every registry changes state the same way: it reads a whole file, changes the list in memory, and writes the whole file back. Atomic writes stop a crash from leaving a half-written file, but they do nothing for two processes that overlap. Both read the same old content, and the later write wipes out the earlier one. Nothing reports it.

This was reproduced with real processes on the current code (Linux sandbox):

| Experiment | Expected | Stored | Lost |
| --- | --- | --- | --- |
| 2 processes, 100 `add_task` calls each, two runs | 200 | 101 and 100 | 99 and 100 |
| 4 processes, 100 `add_task` calls each, two runs | 400 | 108 and 110 | 292 and 290 |
| 12 parallel `aic task create` commands, three runs | 12 | 2 in every run | 10 in every run |

In the CLI runs all 12 commands exited with status 0 and printed a task ID. `aic validate` then reported "Validation passed", because a lost task leaves nothing behind that could be inconsistent. The loss is silent. Timing on Windows may differ, and the Windows replace can also fail outright if another process has the file open (see Risks), but the overwrite itself does not depend on the platform.

The problem is wider than lost items. A command checks and then writes. `aic task start` checks readiness, writes an attempt record, moves the task and reconciles the goal. Two processes that start the same task at the same moment can both pass the readiness check. This was reasoned from the code and not reproduced.

## Facts about the current code

Each item was checked by reading the code or by running it.

- Every registry operation (`add_task`, `update_task_status`, `add_goal`, `open_attempt`, and the rest) is load, change in memory, then `write_text_atomic`. Its docstring says it is not a lock.
- A mutating command can write up to three files. `aic task start` writes `executions.json`, then `tasks.json`, then `goals.json` when it reconciles the goal. `aic goal status` rewrites `goals.json` (G2).
- The CLI has nine commands that write state: `project add`, `goal create`, `goal status`, and `task create`, `ready`, `start`, `complete`, `fail` and `requeue`.
- Seven commands only read: `doctor`, `project list`, `goal list`, and `task list`, `status`, `readiness` and `history`. `validate` also only reads, but it reads four files and wants them to agree.
- The execution coordinator (library) uses the same registry operations. It cannot be reached from the CLI yet (G6).
- Runtime code is standard library only. The tool supports Python 3.11 to 3.14 and runs on Windows (the maintainer's platform) and Linux.
- Killing a process mid-write leaves at most a stale `.<file>.<id>.tmp` file, and never a damaged state file.

## Requirements

1. No silent loss. Concurrent `aic` processes must not overwrite each other. A process that cannot proceed must fail visibly and change nothing.
2. The unit of protection is a whole command, because commands check and then write.
3. A process that dies, including by `kill -9` or power loss, must not leave the tool locked.
4. Standard library only, working on Windows and Linux.
5. No change to the state file shapes and no schema version bump.
6. No weakening of crash safety (INV-16 and atomic writes).
7. A new command must not be able to skip the lock by accident.
8. The lock must never be held while an adapter runs, once adapters exist. A long run would block every other command.

## Options

**A. One exclusive OS lock for the data directory, held for one CLI command (recommended).** A lock file in the data directory is locked with the operating system's file locking for the duration of a command. Other `aic` processes wait, with a time limit, and then fail with a clear error.

- Pro: protects the whole command, so check-then-act and multi-file sequences are safe (requirement 2).
- Pro: the operating system releases the lock when the process dies, so there is no stale lock (requirement 3).
- Pro: one lock means no ordering rules and no deadlock between processes.
- Con: two platform branches, `fcntl` and `msvcrt`, and the Windows branch has not been run.
- Con: coarse. Writers wait for each other, which is fine at this scale.

**B. A lock per state file around each registry operation.**

- Pro: finer grained.
- Con: it does not protect a command. Two `aic task start` processes can still both pass the readiness check, because the check happens before any file lock is taken. Lost updates to one file would stop, but check-then-act would not.
- Con: three files in one command need a fixed lock order to avoid deadlock.

**C. An optimistic check at save time.** Remember what the file looked like when it was read, and refuse to replace it if it changed.

- Pro: standard library only, no platform code, no lock file.
- Con: the check and the replace are two steps, so a small window remains and the loss is still possible. It also needs retry logic and does nothing for check-then-act across several operations.

**D. A lock file created exclusively, holding an owner and a time.**

- Pro: portable, with no `fcntl` or `msvcrt`.
- Con: a process killed while holding it leaves a stale lock that nothing releases. Detecting a dead owner needs platform-specific process checks, or a person has to delete the file. This breaks requirement 3.

**E. Do nothing and document single-process use.**

- This is the status quo. It is only safe while a person never runs two commands at once, and the experiment above shows the failure is silent. Adapters, a second terminal or a scheduled job would each break that assumption. Rejected as the long-term answer.

## Recommendation: Option A

**The lock.** `aic_control_centre/locking.py` provides `state_lock(data_dir, timeout)`, a context manager. It opens `.aic.lock` in the data directory and takes an exclusive lock on one byte: `fcntl.flock` on Unix-like systems (tested on Linux only), `msvcrt.locking` on Windows. It retries every 20 ms until the timeout, then raises `StateLockError`. The file is never deleted, so there is nothing to clean up.

**Where it is taken.** In `main`, around `_run`, once per `aic` process. Library functions do not lock. A second acquisition in the same process is a programming error and raises `StateLockError`, instead of waiting for itself.

**Which commands.** Every command takes the lock except an explicit read-only list: `doctor`, `project list`, `goal list`, and `task list`, `status`, `readiness` and `history`. `validate` takes it, because it reads four files and should see them agree. The default is to lock, so a new command is protected until someone decides it is read-only. A test lists every command the parser knows and fails if one is not classified.

**Failure.** If the lock is not available within 10 seconds, the command changes nothing and prints `Error: another aic process is using the state files (waited 10s).`, with exit status 1. The timeout is a constant, with no setting, to avoid another unused configuration field (G7).

**Readers that do not lock.** A read-only command sees one file at a time, and each file is always complete, so it never sees a half-written file. It can see two files at different moments, which is harmless for a listing.

**The coordinator.** The coordinator CLI that comes with Phase 3 must take the lock only around its state reads and writes, such as admission and start, and the outcome record. It must not hold it while an adapter runs.

**What it does not do.** It does not protect against anything other than `aic` processes, such as a person editing a JSON file or a cloud sync tool. It does not work reliably on network file systems. It does not change INV-16, and it does not address G11.

**A spike.** A throwaway script, not committed, wrapped `main` in a lock of this shape. On Linux, 12 parallel `aic task create` commands stored 12 of 12 tasks and 40 parallel commands stored 40 of 40, in 3.1 seconds, with every command exiting 0. Without the lock, 12 parallel commands stored 2. A second process with a 1 second timeout failed with the clear error while the lock was held. After the holder was killed with `kill -9`, the next command acquired the lock and ran in 0.08 seconds. None of this was run on Windows.

Tests it would need:

- Many processes adding tasks at once lose none, in the registry and through the real CLI.
- A process that cannot get the lock within the timeout changes nothing and exits 1 with the clear error.
- A lock holder that is killed releases the lock.
- A second acquisition in the same process raises `StateLockError`.
- A read-only command does not wait for a held lock.
- Every command the parser knows is classified as locking or read-only.
- The lock file is created in the data directory and not anywhere else, and the suite does not create one in the default data directory.

## Risks

- **Windows is unverified.** `msvcrt.locking` is documented to raise `OSError` when the bytes cannot be locked. Whether the lock is released as soon as the process is terminated, and how two handles in one process behave, have to be checked on Windows. If they behave differently, the fallback is Option D behind the same interface, with a documented stale-lock step.
- **Replace can still fail on Windows.** A read-only command that does not lock can hold a state file open at the moment a writer replaces it, and `os.replace` can then fail with a permission error. The old file is left intact, and the command reports an error, so nothing is lost. A short bounded retry in `write_text_atomic` would make it rare. It can only be tested with a simulated error here.
- **A stuck holder.** A process that is suspended while holding the lock makes every other command fail after 10 seconds. That is a visible error and not a hang, but it is a new way for the tool to refuse work.
- **Polling, not queueing.** Waiters retry every 20 ms, so order is not guaranteed. The spike's 40 parallel commands all finished, but heavy contention could starve one waiter until its timeout.
- **Timing in tests.** Tests that depend on processes overlapping can be flaky. They should use a barrier and generous timeouts.

## Open questions for the maintainer

1. Is a fixed 10 second timeout acceptable? Recommendation: yes, as a constant, with no setting.
2. Should read-only commands wait for the lock too? Recommendation: no, except `validate`.
3. Should the default be to lock, with an explicit read-only list? Recommendation: yes, because a forgotten command is then safe.
4. Should the bounded retry on a Windows permission error in `write_text_atomic` be part of this work? Recommendation: yes, as its own small step after the lock.
5. If `msvcrt.locking` misbehaves on Windows, is Option D with a documented stale-lock step an acceptable fallback? Recommendation: decide after the first Windows check.

## After this decision

Once the note is approved, the build would go in small steps: the lock module and its tests, with subprocess tests; wiring it into `main` with the read-only list and its classification test; the end-to-end concurrent CLI tests; the retry in `write_text_atomic`; and the documentation, including an invariant that every writing command runs under the lock. The maintainer would run the concurrency tests on Windows and, once, a manual run of 12 parallel commands. The transition log, the other half of G4, remains a separate decision.
