# Design Note: Stopping the Child of an Adapter, and a Memory Limit for It

**Status: Proposed. Not accepted.** This note takes what is left of G13 in [STATUS.md](STATUS.md) for the child of a process adapter on Windows: the child keeps running when AIC is killed hard, processes that a child left behind are not stopped after a normal exit, and nothing limits what the child uses. It is based on measurements on one machine, which are in the Evidence section. It proposes a Windows job object and a memory limit, and it leaves out a limit on CPU time, because the one trial of that did not work. Nothing in this note is built.

## Problem

AIC runs the adapters that do real work (`inspect`, `pysyntax` and `gitstate`) as child processes, so that a crash or a hang of a child does not take AIC with it. [PROCESS_ADAPTERS_DESIGN.md](PROCESS_ADAPTERS_DESIGN.md) built the timeout, the output caps and the stopping of the tree. Four cases are still open, and G13 lists them:

- If AIC is killed hard, the child and what it started keep running until they end, and the task stays `running` with its attempt open.
- After a normal exit of the child, a process that it left behind is stopped on Linux and is not stopped on Windows.
- `taskkill /F /T` stops the tree as it is when it runs, so a process that is started at that moment can escape.
- Nothing limits the memory or the CPU time of a child. The 60 seconds, the 1 MiB of output and the 64 KiB of error output are guesses.

## Evidence

The numbers marked Windows were observed by the maintainer under Git Bash with Python 3.14.3, with a script that printed no name of a project and no path and changed nothing that is tracked. It made 48 checks with an expected answer, and 47 came out as expected.

1. **The real children are small and quick.** The script ran each child as the adapter starts it, on the 11 of the 15 directories below the folder of the repository that the snapshot limit lets through. Python started and stopped on its own took 0.06 seconds of wall time, 0.05 seconds of CPU time and 18.8 MiB at its peak. All 33 runs exited with status 0 and printed one answer.

   | Child | Wall time, median and most | CPU time, median and most | Peak working set, median and most |
   | --- | --- | --- | --- |
   | `inspect` | 0.17 s and 0.37 s | 0.17 s and 0.36 s | 24.8 MiB and 25.8 MiB |
   | `pysyntax` | 0.39 s and 3.48 s | 0.25 s and 1.81 s | 26.9 MiB and 58.0 MiB |
   | `gitstate` | 0.14 s and 0.18 s | 0.14 s and 0.16 s | 24.9 MiB and 32.9 MiB |

   The peak commit of any child was 46.0 MiB. The slowest run was `pysyntax` on one project, with 3.48 seconds, which is under 6% of the 60 seconds of the adapter. No run was over 60 seconds. The 4 projects over the snapshot limit were not run, because no adapter would start a child for them.
2. **A job object with kill-on-close stopped the child after a hard kill.** A small parent process made a job object with the kill-on-close flag, started a child, put it in the job and was then killed with `TerminateProcess`. The child was put in the job in 5 of 5 trials, and it was not running 1 second after the kill in 5 of 5. The same child without a job was still running 4 seconds after the kill in 5 of 5. The test child writes a heartbeat to a file, and it was running before the kill in all 10 trials.
3. **A memory limit of a job object worked.** A child that asked for 300 MiB, in a job with a limit of 100 MiB for a process, did not get it and ended with status 1. The same child without the limit got it.
4. **A limit on CPU time did not work in the one trial.** A child that used the CPU for 4 seconds, in a job with a per-process user time limit of 1 second, ran to the end, in 4.6 seconds. The child without the limit also ran 4.6 seconds. That is the one check that came out unexpected. The cause is not known. The sizes of the two structures were as expected, and the memory limit through the same call worked, which makes a wrong structure less likely and does not rule out a mistake of the script. How Windows applies that limit was not looked up.
5. **Earlier, with the real adapter.** A hard kill of `aic task run --target inspect` left the child running for more than 30 seconds in 2 of 5 trials, and the child ended about a second after the kill in the other 3 (G13). The reason is not known. The trials above did not reproduce it, because the test children have no pipes and do no real work.
6. **No child that AIC ships starts a process.** `inspect_project.py`, `check_python.py`, `git_state.py` and `child_request.py` have no use of `subprocess`, `Popen` or `os.system`. The only processes in a run are the child and the one that AIC starts.
7. **A failed task fails its goal for good** ([SNAPSHOT_LIMIT_DESIGN.md](SNAPSHOT_LIMIT_DESIGN.md)). A child that is stopped for its memory ends as a failed outcome, as one that times out does today, so a limit that is too low would fail goals.

**Not known.** What happens to a child that starts a process before it is put in a job, because Python cannot start a process suspended. Whether closing a job after a normal exit stops a process that the child left behind, which follows from the documentation and was not tried. A job when AIC itself runs inside a job, which Windows 8 and later allow and earlier versions do not. How much memory `pysyntax` uses on a project near its limits of 10,000 files and 64 MiB, which the sample did not have. Linux and macOS.

## Facts about the code

- `ProcessAdapter._run` starts the child with `subprocess.Popen`, in its own process group (`CREATE_NEW_PROCESS_GROUP` on Windows), in an empty folder made by `tempfile.TemporaryDirectory` with the prefix `aic-run-`, with a short environment.
- It polls the child. When the child is still running at the end, or after a timeout, an output cap or an interrupt, `_kill_tree` runs `taskkill /F /T /PID` on Windows and `killpg` elsewhere, and reaps the child. `_stop_group` does nothing on Windows.
- A child that exits with a status that is not 0 gives a failed outcome with `adapter exited with status <n>` and a short note from its error output.
- The defaults are 60 seconds, 1 MiB of standard output and 64 KiB of error output, and each can be set per adapter when it is made.
- A hard kill of AIC skips the cleanup of the folder, so an empty `aic-run-` folder stays in the temporary folder of the system. Each of the 5 kills on Windows left one.

## Requirements

1. It uses the standard library only. `ctypes` is part of it.
2. Nothing changes on Linux and macOS, where the process group already stops the tree after a normal exit.
3. On Windows, the child and everything it started are gone after a run, however AIC ends.
4. A limit is used only if it has been seen to work.
5. A problem with the new machinery does not stop a run that would have run before. It is said where a person can find it.
6. The existing tests pass unchanged, and the new tests do not need Windows to run, apart from those that say that they return early.

## Options

- **A. Do nothing.** The limits stay documented. Rejected only if the case matters, which is open question 1.
- **B. A job object with kill-on-close for every child.** Recommended. Closing the last handle of the job ends every process in it, so a hard kill of AIC, a normal exit with a process left behind, and a process that starts during the stopping are all covered. It was seen to work on a test child (evidence 2).
- **C. A limit on the memory of a process in the same job.** Recommended. It was seen to work (evidence 3), the real children use at most 58.0 MiB, and it bounds a project whose source was made to make the compiler use a lot of memory, which was not tried.
- **D. A limit on CPU time in the same job.** Rejected. It did not work in the one trial (evidence 4), and every child that AIC ships has one thread, so the timeout in wall time bounds its CPU time already. Reopen it with the first adapter that uses more than one thread, after the cause of the trial is known.
- **E. Keep `taskkill /T` only.** Rejected as the answer. It leaves a hard kill and the race of G13 as they are. It stays as it is, under the job.
- **F. Start the child suspended and resume it after it is in the job.** Rejected. Python does not give the handle of the thread, and the other ways of resuming a process use calls that this note did not look into. No child that AIC ships starts a process (evidence 6), so the gap between the start and the assignment does not matter for them. It matters for an adapter that does.
- **G. A watchdog process that kills the child when AIC dies.** Rejected. It is one more process, and it can die too.
- **H. Remove the old `aic-run-` folders.** Rejected for now. The folders are empty and small, and removing things in the temporary folder of the system is a decision of its own.
- **I. The same for Linux and macOS, with `PR_SET_PDEATHSIG` and `RLIMIT_AS`.** Not in this change. It has no evidence from the maintainer's machine, and `PR_SET_PDEATHSIG` follows the thread that started the child and not the process. It can be its own note.
- **J. A library such as `psutil` or `pywin32`.** Rejected. AIC has no dependency at run time.

## Recommendation

1. **A module `execution/job.py`** that makes a job object with `ctypes` on Windows and gives back nothing elsewhere. It has a function that makes a job with the kill-on-close flag and an optional limit on the memory of a process, a method that puts a started child in it, and a method that closes it. The structures use types of fixed width, so their sizes can be tested on any system.
2. **`ProcessAdapter._run` uses it on Windows.** It makes the job before the child starts, puts the child in it right after `Popen` returns, and closes it in the `finally` block, after the child has been stopped or has ended and before the folder is removed. `taskkill /F /T` stays for the timeout, the cap and the interrupt.
3. **A limit of 512 MiB of memory for a process,** as a constant, and a parameter of `ProcessAdapter` that sets it per adapter, with `None` for no limit. That is about 11 times the largest peak commit that was seen. A child that is stopped by it ends as a failed outcome with the status that Windows gives, as any child that fails does.
4. **A best effort.** If the job cannot be made or the child cannot be put in it, the run goes on as it does today, and nothing is added to the reason of the outcome. The documentation says that the guarantee is of Windows, and open question 3 says how else it could be shown.
5. **No limit on CPU time,** and no change of the timeout, the output caps or the environment of the child.
6. **Linux and macOS are not changed.**
7. **The `aic-run-` folders are not removed,** and G13 keeps saying so.

## What it does not do

- It is not a sandbox. It does not limit what files a child reads or writes, the network, the handles, the number of processes or the CPU time.
- It does not explain why a child survived in 2 of 5 trials with the real adapter. It would stop such a child if it is running when AIC dies.
- It does not help an adapter that starts a process before it is put in the job.
- It does not make a killed run recover. The task stays `running` with its attempt open, which is the safe shape, and `aic task requeue` handles it.

## Tests the build needs

- **The module.** On any system, the sizes of the two structures are 144 and 72 bytes on a 64-bit build, the memory in MiB becomes bytes, the flags that are set are the ones that were asked for, and the function gives back nothing off Windows. On Windows, and returning early elsewhere: a child in a job is gone after the job is closed, a child that starts its own child has both gone, and a child that asks for more than the limit does not get it.
- **The wiring,** with the job replaced by a recording fake, so that it runs on Linux: the job is made before the child starts, the child is put in it right after, and it is closed after the child is gone, on a normal end, on a timeout, on an output cap, on an interrupt and when the assignment raises. The memory limit that is passed is the one of the adapter. A job that cannot be made, or an assignment that fails, leaves a run that completes as before. Nothing is made when `os.name` is not `nt`.
- **No change.** The existing tests of the process adapter pass without changes, and the output of a run through the real command line is the same as before.
- **Mutations.** The flag, the limit and its conversion to bytes, the order of the assignment and the start, the close in the `finally` block and the fallback.
- **On Windows.** A step that hard-kills `aic task run --target inspect` in 5 trials, as the earlier script did, and expects the child gone in all 5, a run of a `ProcessAdapter` with a command that asks for more memory than the limit, which must give a failed outcome, and the three real adapters run again on the same projects, which must take about as long as before.

## Risks

- A limit that is too low fails real runs, and a failed task fails its goal. 512 MiB is 11 times what was seen, and `pysyntax` on a project near its limits was not measured.
- The job is made by AIC, so a machine that forbids it, or a version of Windows that does not nest jobs, gets today's behaviour with nothing said, until open question 3 is settled.
- Closing the job ends everything in it, including a process that an adapter meant to leave. No adapter does.
- The limit is of the memory that a process has asked for, and not of the memory that it uses. A process that asks for little and uses much is not limited.
- It was tried on test children that have no pipes. It was not tried on a real run.

## Open questions

1. **Should it be built at all?** Recommendation: yes. It closes the one open case of G13 that has evidence on this machine, it is small, and it needs no dependency. Doing nothing is a fair answer if hard kills are rare.
2. **What should the memory limit be?** Recommendation: 512 MiB, as a constant, and review it when a real run is stopped by it.
3. **Should a failure to make or use the job be shown?** Recommendation: no, as in decision 4, because the guarantee is an extra over what exists. If it is wanted, `aic task targets` or `aic doctor` could say whether the job is in use, and that is a separate change.
4. **Windows only?** Recommendation: yes for now, and a note for the others when there is evidence.
5. **Should the old `aic-run-` folders be removed?** Recommendation: no.
6. **Should the timeout change?** Recommendation: no. The slowest run was 3.48 seconds, and the 60 seconds is generous for what was seen. Reopen it when a project near the limits of the snapshot has been timed with `pysyntax`.
7. **Should the CPU time be limited?** Recommendation: no, for the reasons of option D. A step that finds out why the trial failed can be run before an adapter with threads is added.

## Recommended order

1. Add `execution/job.py` and its tests.
2. Wire it into `ProcessAdapter._run`, with the tests of the wiring.
3. Run the Windows step, and record it.
4. Write the documentation, and change G13.
