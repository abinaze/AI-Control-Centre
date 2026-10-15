# Design Note: Out-of-Process Adapters, Timeouts and Limits

**Status: Stages 1 and 2 are built.** The Windows check settled Decision 3, and the recommendations below were followed. What was built, and what was found while building it, is at the end of this note. It is the second design note of Phase 3 in [ROADMAP.md](../ROADMAP.md), after [COORDINATOR_CLI_DESIGN.md](COORDINATOR_CLI_DESIGN.md). It covers how the CLI can run an adapter that does real work without trusting that adapter to stop. Permissions are a separate note and are only given a hook here.

## Problem

`aic task run` runs the adapter inside the CLI process, on the same thread, with no time limit. The only adapter is `noop`, which cannot hang. Any adapter that does real work can.

What happens today was checked on the current code (Linux sandbox) by running the real command with a fake adapter that sleeps for five minutes:

- **Nothing stops the hang.** The command waits until a person acts. Nothing in AIC has a clock on an adapter.
- **Ctrl-C ends the process.** The parent saw the process die with `KeyboardInterrupt`, and a raw traceback was printed. The task stayed `running` with its attempt open. `aic validate` passed, the lock was free at once, and `aic task requeue` recovered the task.
- **A hard kill (SIGKILL) left the same state**, without a traceback.

So the crash shape is safe, as INV-16 intends. What is missing is a way for AIC to stop a runaway adapter by itself, and to record why.

Moving the adapter into a child process makes a timeout possible, and a second set of facts follows. These were checked with `check_kill.py`, a stdlib script, on Linux:

- **Killing the child does not kill what the child started.** After `Popen.kill()` on a child, its own child was still running. Stopping the whole tree took a new session for the child and `killpg` on its group, which did stop both.
- **A timeout works.** `communicate(timeout=1)` raised after 1.00 seconds, and the child was reaped after the kill.
- **Output must be read in chunks.** `communicate()` kept all 20,000,000 bytes of a finite output in memory. A child that printed forever was stopped after 102,400 bytes with a cap of 100,000, by reading 4 KiB at a time.
- **A JSON request and outcome with non-ASCII text round-tripped through stdin and stdout** as UTF-8 bytes.

The same script was run on Windows (Python 3.14.3). `Popen.kill()` left the child's own child running there as well. `taskkill /F /T` stopped the child and its own child, and so did a job object with kill-on-close. `communicate(timeout=1)` timed out after 1.01 seconds and the child was reaped after the kill. A child that never stopped printing was stopped after 102,400 bytes with a cap of 100,000. The JSON request and outcome with non-ASCII text round-tripped as UTF-8 bytes.

## Facts about the current code

- `ExecutionCoordinator` calls `adapter.execute(request)` synchronously and converts an exception, an invalid result or a result for another task into a `failed` outcome. It catches `Exception`, so `KeyboardInterrupt` is not converted. This is why the traceback appeared.
- An adapter is any object with `execute`. An out-of-process adapter is therefore just another adapter, and the coordinator needs no change. A timeout would be returned as a `failed` outcome, and recorded under the state guard against the attempt that started (INV-21, INV-22).
- `ExecutionRequest` carries only a task ID and a target. Nothing from a task, such as its title or description, reaches an adapter today.
- Adapters are registered in code by `build_adapter_registry`. Nothing is loaded from configuration.
- `run_task` and `main` do not catch `KeyboardInterrupt`.
- There are no permissions, no limits and no control over the environment an adapter sees.

## Requirements

1. AIC, not a person, stops a hung or runaway adapter.
2. A stopped adapter leaves no processes behind, including the ones it started.
3. A timeout is recorded as a `failed` outcome with a reason, under INV-21 and INV-22.
4. Output is bounded.
5. Nothing from a task is ever placed in a command line or an environment variable.
6. The child sees a minimal environment. Nothing is inherited that is not on a short list written in code.
7. Windows and Linux, standard library only.
8. Nothing here pre-decides permissions.

## Decisions

### Decision 1: Where the timeout lives

**Option 1A: a `ProcessAdapter` wrapper.** An ordinary adapter whose `execute` runs a fixed command in a child process, with a timeout and an output cap, and returns the outcome. The coordinator is unchanged. Each target is configured in code with its command and its limits.

**Option 1B: a timeout in the coordinator.** Run `execute` on a thread and give up after a deadline. Python cannot stop a running thread, so the work would keep running with nobody watching it. Rejected.

**Option 1C: a cooperative deadline.** Pass an adapter a deadline and trust it to check. This is useful for well-behaved adapters and is not a safety control. Rejected as the mechanism, and still possible as an extra.

**Recommendation: 1A.**

### Decision 2: The contract with the child

**Option 2A: JSON over stdin and stdout.** The command is a fixed argument list in code, such as the running interpreter with `-m` and a module name. AIC writes one JSON object, `{"task_id": ..., "target": ...}`, to the child's stdin as UTF-8 bytes. The child writes one JSON object, `{"outcome": ..., "reason": ...}`, to stdout and exits 0. Anything else is a `failed` outcome: a non-zero exit, output that is not valid JSON, an unknown outcome, or output over the cap. A bounded part of stderr is added to the failure reason so it can be diagnosed.

**Option 2B: arguments on the command line.** Task data would travel in argv. Rejected: it invites injection, has length limits, and breaks Requirement 5.

**Option 2C: files in a temporary directory.** More moving parts. It may be wanted later for large payloads.

**Recommendation: 2A.**

### Decision 3: Stopping the whole tree

**Option 3A: `taskkill /F /T` on Windows, and a new session with `killpg` elsewhere.** Standard library only. `taskkill` stops the tree as it exists when it runs, so a process started during the kill could escape. Nothing stops the tree if AIC itself is killed.

**Option 3B: a job object with kill-on-close on Windows, through `ctypes`.** The operating system stops every process in the job when its handle closes, which also covers AIC being killed. The same mechanism later gives memory and process-count limits. The cost is `ctypes` code that cannot be tested on Linux, and a child must be assigned to the job before it can start its own children.

**Option 3C: `Popen.kill()` only.** It left the child's own child running in the Linux check. Rejected.

**Recommendation: 3A, and a job object only if limits need it.** Both `taskkill /F /T` and a job object worked on Windows. With both working, 3A is simpler: it needs only the standard library, and a job object has a start-up race, because a child can start its own children before it is assigned to the job. The cost of 3A is that nothing stops the tree if AIC itself is killed.

### Decision 4: Limits

Guaranteed on both platforms, with the standard library: a wall-clock timeout, and a cap on stdout and on stderr. Not portable: CPU and memory limits. POSIX has `resource` limits that must be set in the child before it runs. Windows needs a job object.

**Recommendation:** build the timeout and the output cap now, with defaults of 60 seconds, 1 MiB for stdout and 64 KiB for stderr, set per target in code. Do not build CPU or memory limits until a real adapter needs them, and say in the documents that they are not enforced.

### Decision 5: Environment and working directory

The child gets an environment built from a short list of names written in code, for example the system search path and, on Windows, the system root, which Python can need to start. It never gets AIC's data directory setting or anything else from the parent. The child runs in a new empty temporary directory that is removed afterwards. The project path is a permissions decision for the next note.

### Decision 6: Interrupts

Running the child in its own session means a Ctrl-C in the console no longer reaches it. A `ProcessAdapter` that does nothing would leave an orphan running after the person has pressed Ctrl-C. So the adapter stops the tree in a `finally` block when it is interrupted, and `run_task` catches `KeyboardInterrupt` only to print a message instead of a traceback and to exit with status 130: the task is still running, and `aic task complete`, `fail` or `requeue` recovers it.

An interrupted run is not recorded as an outcome. The crash shape is already safe and recoverable, and recording would need the lock at a moment the person is trying to stop the command.

**Recommendation: as described.**

### Decision 7: No real adapter yet

**Recommendation:** ship the `ProcessAdapter` machinery and test it with child scripts that live in the tests. Ship no real process adapter until the permissions note exists. `noop` stays the only target.

## Recommended order

1. **`ProcessAdapter`**, library only: the contract, the timeout, the output cap, the environment, the tree kill for each platform as Decision 3 settles it, and the interrupt handling.
2. **`run_task`**: catch `KeyboardInterrupt` and print the message.
3. **Documentation.**

Tests, using child scripts in the tests:

- A child that returns a valid outcome produces that outcome.
- A child that sleeps past the timeout is stopped, the outcome is `failed` with a reason that names the timeout, and a process the child started is dead afterwards.
- A child that prints forever is stopped at the cap and fails.
- A child that exits non-zero, prints invalid JSON, or returns an unknown outcome fails, and stderr appears in the reason.
- A non-ASCII reason round-trips.
- The child's environment contains only the allowed names. A variable set in the parent is absent in the child.
- The working directory is not the current directory and is gone afterwards.
- An interrupt stops the tree.
- Through the CLI: a timed-out run records `failed` with the right attempt, and `aic validate` passes.

## Risks

- **Windows behaviour rests on one check.** `check_kill.py` passed on one machine. The adapter's own tests run on Windows when the maintainer runs the suite there.
- **AIC being killed can leave an orphan.** On Linux, the child and its tree keep running if AIC is killed with SIGKILL. On Windows only a job object prevents this. The state is still the safe crash shape, and the orphan runs on until it ends.
- **The default limits are guesses.** They are set per target, so a real adapter can change them.
- **A cap can fail a legitimate run.** The contract keeps the result small, so a large output is more likely a mistake than a result.
- **A child stuck in uninterruptible I/O may not die at once.** The adapter waits a bounded time after the kill and then reports that the child did not exit.
- **Stderr in a failure reason can hold sensitive text.** The security policy already says this about reasons.

## Open questions for the maintainer

1. Build the timeout in a `ProcessAdapter` wrapper (Option 1A)? Recommendation: yes.
2. Use JSON over stdin and stdout with a fixed command in code (Option 2A)? Recommendation: yes.
3. Run `check_kill.py` on Windows and paste the output, so Decision 3 can be made. Done: it passed, and Decision 3 follows the recommendation.
4. Are the defaults acceptable: 60 seconds, 1 MiB of stdout and 64 KiB of stderr, per target in code? Recommendation: yes.
5. Defer CPU and memory limits until a real adapter needs them? Recommendation: yes.
6. Stop the tree on an interrupt and print a message, without recording an outcome? Recommendation: yes.
7. Ship no real process adapter until the permissions note exists? Recommendation: yes.

## Stages 1 and 2: built

Everything in this section was observed on Linux, except what is said about Windows.

- `execution/process.py` holds `ProcessAdapter(command, description=, timeout_seconds=60, stdout_limit=1 MiB, stderr_limit=64 KiB)`. The command is a fixed list in code. The request goes to the child as one JSON object on standard input, and the child answers with one JSON object on standard output and exit status 0.
- Anything else is a failed outcome with a reason: `adapter timed out after N seconds`, `adapter output exceeded N bytes`, `adapter error output exceeded N bytes`, `adapter exited with status N`, `adapter output was not valid UTF-8`, `adapter output was not valid JSON`, `adapter output was not a JSON object`, `adapter reported an unknown outcome`, or `adapter reason was not text`. A failure includes up to 300 characters of the child's standard error. A reason is shortened to 1000 characters.
- The child inherits only `PATH`, `SYSTEMROOT`, `TEMP`, `TMP`, `LANG` and `LC_ALL`, and runs in a new empty temporary directory that is removed afterwards.
- On Linux the child starts in its own session and the whole group is stopped, also after a normal exit, so a process the child left behind is stopped too. On Windows the tree is stopped with `taskkill /F /T` while the child is alive, and nothing is done after a normal exit.
- On an interrupt the tree is stopped in a `finally` block. `aic task run` catches `KeyboardInterrupt`, prints `Interrupted.` and a line saying how to recover, and exits 130. No outcome is recorded, so the task stays `running` with its attempt open, which `aic task requeue`, `complete` or `fail` recovers.
- Nothing registers a process adapter, so the real CLI cannot reach one yet. It was run through a small harness that registers one. A child that sleeps was stopped after 2 seconds: `Result: failed`, `Reason: adapter timed out after 2 seconds`, exit status 1, the attempt closed as `failed` with the same reason, and `aic validate` passed. Ctrl-C with a live child and grandchild ended with exit status 130 and the message, the task `running`, the attempt open, `aic validate` passing, and both processes gone. Ten timeout and interrupt runs left no process behind.
- A bug was found by a mutation test. With the group stop removed, a process left behind held the output pipe open, and the adapter then closed a pipe that a reader thread was still blocked on, which waits forever. On Windows, where nothing is stopped after a normal exit, this could have hung the adapter. It now closes only the pipes whose reader has finished, and a test pins it with the group stop disabled.
- The suite grew from 448 to 480 tests. Changes made one at a time were each caught by a test: no group stop, pipes closed unconditionally, the whole environment inherited, the current directory used, a non-zero exit ignored, an unknown outcome accepted, a long reason not shortened, stderr left out of a failure, the request not sent, the interrupt not caught, and the interrupt exiting 1. Two other changes, leaving out the stop call in the cleanup path, can only be seen on Windows, because on Linux the group is stopped in two places.
- Not built: a process adapter that does real work, permissions, a job object, and CPU and memory limits.

## After this decision

No real process adapter is built until the permissions note exists. If a different option is chosen anywhere above, this note is revised and approved again before any further code.
