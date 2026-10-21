# Design Note: The First Real Execution Adapter

**Status: Proposed.** Nothing described here is built. It decides what the first adapter that does real work on a project may receive, where it runs, what it may touch, what it records and what it does. It needs the maintainer's decisions before any code is written. The evidence was observed on Linux, and the Windows observations are in a section of their own after it.

## Problem

Today the only adapter is `noop`, which does no work. The process adapter ([PROCESS_ADAPTERS_DESIGN.md](PROCESS_ADAPTERS_DESIGN.md)) can run a fixed command in a child process, but nothing registers one. Permissions ([PERMISSIONS_DESIGN.md](PERMISSIONS_DESIGN.md)) decide which projects may use a target. They do not say what a target may touch, and they were left unfinished on purpose until the first real adapter was designed.

The first adapter is the first code in AIC that would act on a person's files. Four questions have to be answered before any code: what it receives, where it runs, what it may touch, and what it does. The answers also decide what a later adapter, one that writes, will be allowed to build on.

## Evidence

All of this was run on Linux with the real code and temporary directories.

1. **What a process child receives.** A `ProcessAdapter` child was given the request and it read its own surroundings. Standard input held only `task_id` and `target`. Its working directory was an empty temporary directory. Its environment held `PATH` and `LC_CTYPE`, which Python itself sets. It knows nothing about a project.
2. **What a process child can reach.** The same child, with no `HOME` in its environment, found the real home directory from the password database. It read a file in a directory that it had not been given, wrote a file into another directory, and opened a connection to a local TCP listener. The empty working directory and the short environment list keep the child tidy. They do not confine it.
3. **Project names are not unique.** Two different directories, both named `app`, were registered with `aic project add`. Both were accepted and both were listed as `app`. A goal was created for `app`, `aic validate` passed, and a lookup by name returned the first directory. Goals and grants identify a project by its name only, so a grant for `app` does not say which directory it covers.
4. **A deleted project directory is not noticed.** After a registered directory was removed, `aic validate` still passed and `aic project list` still showed it. The only existence checks in the code run when a project is registered.
5. **What a snapshot of a project costs.** Listing every file with its size and modification time took 0.007 seconds for 566 files (1.6 MiB), and 0.146 seconds for 2,040 files (25.7 MiB). Reading and hashing every file took 0.012 and 0.377 seconds. These are Linux times with a warm cache.
6. **A shipped child module needs the installed package.** A child that imports `aic_control_centre` worked when the package was installed and failed with `ModuleNotFoundError` when it was reachable only through `PYTHONPATH`, because the allowlist does not pass `PYTHONPATH` on.
7. **Results have no home but the reason.** The attempt record keeps a `reason` of at most 1000 characters. Nothing stores the output of a run. The repository has `logs/`, `goals/` and `reports/` folders that hold only a `.gitkeep` and that no code uses.

## Windows observations

These were observed on Windows with Python 3.14.3, by the maintainer running the check script in Git Bash. The directory that was measured for the snapshot was the AIC repository.

1. **Paths.** A project path with spaces and a non-ASCII character went through the child and came back as the same text, through UTF-8 on standard input and output.
2. **What the child sees.** Standard input held only `task_id` and `target`, and the working directory was an empty temporary directory, as on Linux. The environment held `PATH`, `SYSTEMROOT`, `TEMP` and `TMP`.
3. **What the child can reach.** `os.path.expanduser("~")` returned `~`, so a child with this environment does not find the home directory in the way that the Linux child did. It still read a file by its path in a directory that it had not been given, wrote a file into another directory, and connected to a local listener. The reach is the same on both systems: any path that the user can use. Only the way of finding the home directory differs.
4. **A shipped child module.** A child that imports `aic_control_centre` worked under the allowlist. The package was installed in the active virtual environment.
5. **What a snapshot costs.** The AIC repository, 2,175 files and 5.0 MiB, took 0.282 seconds to list with size and modification time, and 0.616 seconds to read and hash. The time per file is about ten times the Linux time of 0.007 seconds for 566 files. By that rate, listing a tree of a hundred thousand files would take about 13 seconds, which is an estimate and not a measurement.
6. **Modification times.** Twenty same-size rewrites of one file, each made straight after the previous write, changed its modification time five times. So the time advances in coarse steps on this system. This does not say how often a real change would be missed, because the last write of a file is normally long before a snapshot. It does show that size and modification time cannot be trusted alone for a change that comes right after a write.

## Facts about the current code

- `ExecutionRequest` holds `task_id`, `target` and `requires_grant`. An adapter learns nothing else.
- Admission looks up the project of a task, by name, only when the request needs a grant.
- A project is a name and a resolved absolute path. The name is the last part of the path.
- The process adapter's rule is that nothing from a task is ever placed in the command or in the environment. Its input is JSON on standard input.
- An outcome is `completed`, `failed` or the other known values, with a reason that is shortened to 1000 characters.
- The coordinator holds the state lock around the start and around each outcome, and never around the adapter.
- `aic task running` lists a run that stays open, and `aic task requeue` recovers it.

## Requirements

1. The first adapter does nothing that cannot be explained in a sentence, and nothing outside the project directory that it is given.
2. A task is never run against a directory that the person did not mean. The project behind a name must be one directory.
3. Nothing from a task, such as its title or description, reaches a command line or an environment variable.
4. The result can be checked: a person can tell from the outcome what was found.
5. It uses only the standard library and works on Windows and Linux.
6. Grants apply as they are. The adapter needs a grant like any target that is not `noop`.
7. Existing adapters, commands and tests keep working.
8. Every failure is a recorded outcome and never a crash.

## Options

### Decision 1: one directory behind each project name

**1A. Refuse a second project with a name that is already registered, and make `aic validate` report duplicate names (recommended).** `aic project add` would say which path already holds the name. A state that already has duplicates is reported by validation and is not changed.

- Pro: small, and it keeps names as identities for goals and grants, so no schema changes.
- Con: two directories with the same last name cannot both be registered. A person has to rename one directory or leave one out.

**1B. Identify a project by its path in goals and grants.** It removes the ambiguity entirely and it changes every state file. Rejected for now.

**1C. Do nothing.** A grant could then let a run touch the wrong directory. Rejected.

### Decision 2: how the request carries the project

**2A. Add an optional `project_path` to `ExecutionRequest`, filled in by the coordinator from the registry when the start is admitted (recommended).** The default is nothing, so every existing request and test is unchanged. If the project is not registered, or its path no longer exists or is not a directory, admission refuses the request with a reason and writes nothing, as it does for a missing grant. The process adapter sends the path to its child in the JSON on standard input, never in the command or the environment.

- Pro: the path is looked up once, under the state guard, and an adapter cannot read other state.

**2B. The adapter looks the project up itself.** It couples adapters to the state files, reads outside the guard, and lets an adapter read other projects. Rejected.

**2C. Also send the title and the description of the task.** The first adapter does not need them, and they are free text. Not now. A later adapter that needs them decides how to keep them out of commands.

### Decision 3: where the child runs

**3A. In its empty temporary directory, with the project path given on standard input (recommended for the first adapter).** A child that reaches the project has to name its path, and a mistake with a relative path lands in the empty directory.

**3B. In the project directory.** It is what most tools expect. Any relative path then lands in the project, which is harder to audit. The decision for an adapter that runs a tool is for that adapter's note.

**3C. In a copy of the project.** It keeps the real project safe from writes. It costs a copy per run, and any result that matters has to be taken out of the copy again.

### Decision 4: what the adapter may touch

The evidence says that nothing in the process adapter confines a child. The options are about how far to go, and about honesty.

**4A. Read-only by construction, and checked (recommended).** The first adapter is code that AIC ships and that only reads. Around each run AIC lists every file of the project with its size and modification time, before and after, without following links. If anything differs, the outcome is `failed` with the reason `the project changed during a read-only run`. This detects a change inside the project. It does not stop one, and it cannot see a change outside the project.

- Cost: 0.15 seconds for about 2,000 files on Linux, and 0.28 seconds for about 2,200 files on Windows. By those rates a tree of a hundred thousand files would take several seconds on Linux and about 13 seconds on Windows, which is an estimate and not a measurement, and whether to refuse above a number of files is an open question.
- Limit: a person who edits the project while the run goes on causes a false failure. The failure is safe, because the run can be requeued, and the reason says that the cause may be another program.

**4B. An operating system sandbox.** It is the strong answer and it is different for each system: namespaces or a tool such as bubblewrap on Linux, a restricted token or an AppContainer on Windows. It is not standard library and it is a project by itself. Later, if an adapter needs to write.

**4C. A separate operating system user or a container.** Out of scope for a local-first tool.

**4D. Trust the adapter and say so.** It does not fit an adapter that reads real files. Rejected.

In every option a grant is a policy for code that AIC ships. It is not a defence against a hostile program that runs as the same user, and SECURITY already says so.

### Decision 5: what the first adapter does

**5A. `inspect`: report facts about the project directory, read-only (recommended).** It reports the number of files and directories, the total size, the three largest files, and whether a `README` and a `.git` folder exist. It does not follow links. File names are data from the project, so control characters in them are escaped in the reason. It proves the plumbing that every later adapter needs: the grant, the path, the process boundary, the read-only check and the recorded result. It works for any language.

- Con: it is of little use by itself, which is the point of a first step.

**5B. A Python syntax check.** It parses every `.py` file with the standard library and fails with the first files that do not parse. It is checkable and read-only, and it is useful for Python projects only. A good second adapter.

**5C. Run a project's tests or an arbitrary command.** It needs a command per project, and AIC registers adapters in code and does not read configuration. It writes files, and it is the full risk of Decision 4. Not first.

**5D. Write files or apply a patch.** Not before a read-only adapter has proved the machinery.

### Decision 6: where the result is recorded

**6A. In the attempt's reason, up to 1000 characters (recommended).** The summary of `inspect` fits, and `aic task history` already shows it.

**6B. Store the full output in a file.** It needs new storage, a retention rule and care with secrets in output. Not now.

### Decision 7: detecting a dead run

**7A. Leave it for later (recommended).** The adapter runs under a 60 second limit and AIC stops the child itself. A run can be left open only if AIC is killed hard, and `aic task running` already shows how long a task has been running.

**7B. Record the owner of the attempt now.** It needs a new field, a schema change and a check that works on both systems. It belongs after a real adapter has run.

### Decision 8: how it is registered and started

**8A. Register `inspect` in code as a `ProcessAdapter` that runs a fixed command with the current Python and a module that AIC ships. It needs a grant (recommended).** The package has to be installed, which is the documented setup. If it is not, the child fails to import and the run ends as a failed outcome with that message.

**8B. Pass `PYTHONPATH` to the child.** It makes an uninstalled package work. It also puts a variable from the parent into the child. Rejected.

**8C. Run it inside the CLI process.** It has no time limit and no way to be stopped. Rejected.

## Recommendation

Take 1A, 2A, 3A, 4A, 5A, 6A, 7A and 8A. A run of `inspect` would go like this:

    aic permission grant app --target inspect --reason "look at the files"
    aic task run <task-id> --target inspect

    admission:  project app is registered, its path exists, a grant covers it
    start:      the attempt is opened and the task is running
    run:        snapshot the project, start the child with the path on standard
                input, the child reads and reports, snapshot the project again
    outcome:    completed with the facts as the reason, or failed with why
    reason:     files 412, directories 37, size 5.2 MiB; largest ...; README yes; .git yes

The example reason is an illustration of the intended content, not output.

## What this does not do

- It does not stop a hostile program. It makes a read-only adapter that AIC ships, and it checks that the project was not changed.
- It does not cover writing. A write adapter needs its own note, and probably Decision 4B.
- It does not detect a dead run (Decision 7).
- It does not let a task's text reach any command.

## Tests the build needs

- A second project with an existing name is refused, and the message names the path that holds it. `aic validate` reports duplicate names that are already in the state, and changes nothing.
- A request carries the project path, and a request built by hand has none. Admission refuses a project that is not registered, a path that is gone, and a path that is a file, writes nothing and says why.
- The process adapter sends the path only in the standard input JSON. It is not in the command or the environment.
- The read-only check: a child that writes a file in the project, one that changes a file, and one that removes a file each give a failed outcome. A child that changes nothing completes. A change made during the run by another program gives the same failed outcome.
- `inspect` reports the counts, the size, the largest files, and the `README` and `.git` flags. Control characters in a file name are escaped. A link is not followed. A missing or unreadable directory is a failed outcome and not a crash.
- The adapter needs a grant, and `aic task targets` says so. Running it without a grant is refused and writes nothing.
- The reason is shortened to 1000 characters.
- The adapter is stopped at its time limit, with a child that does not exit.
- On Windows: a project path with spaces and non-ASCII characters round trips through standard input, and the read-only check is not fooled by the timestamps that the file system keeps.

## Risks

- **A sense of safety that is not there.** The read-only check detects, it does not prevent, and it sees only the project. The note, the output of `aic task targets` and SECURITY have to say so plainly.
- **Timestamps.** The modification time advances in coarse steps on Windows: only 5 of 20 same-size rewrites made straight after a write changed it. A change that keeps the size can be missed when it comes right after the previous write. Comparing size and time is a floor. A hash of every file closes it, at the cost of reading them: 0.6 seconds for 2,175 files (5.0 MiB) on Windows.
- **Large projects.** A snapshot of a very large tree is slow. A limit is a guess, and it is an open question.
- **False failures.** A person or a program that edits the project during a run fails it. The reason says so.
- **File names are data.** They can hold control characters and very long text. They are escaped and shortened before they are recorded or printed.
- **Links and junctions.** The snapshot and `inspect` do not follow them. On Windows, junctions and other reparse points behave differently from Linux links, and need a check.
- **Name collisions on rename.** Decision 1A makes names unique at the moment of registering. A person who renames a directory later still has the old name in the registry.

## Open questions for the maintainer

1. Make project names unique, with `aic project add` refusing a second one and `aic validate` reporting duplicates (1A)? Recommendation: yes. This is needed before any adapter uses a path.
2. Carry the project path in the request, and let admission refuse a path that is gone (2A)? Recommendation: yes.
3. Run the first adapter in an empty directory, with the path on standard input (3A)? Recommendation: yes.
4. Accept read-only by construction with a before and after check (4A), and say plainly that it is not a sandbox? Recommendation: yes. A sandbox (4B) belongs to the first adapter that writes.
5. Make the first adapter `inspect` (5A), and a Python syntax check the second (5B)? Recommendation: yes.
6. Compare size and modification time only, or also hash the content? Recommendation: size and time plus a content hash, because the Windows modification times advance in coarse steps (see the Windows observations) and a hash cost 0.6 seconds for 2,175 files on Windows. The cost grows with the bytes read, so the limit on project size in question 7 matters more with hashing.
7. Refuse a project above some number of files, or leave it unlimited? Recommendation: unlimited at first, with the time that a snapshot takes reported if it is long. Any number now would be a guess.

## Recommended order

1. Make project names unique and report duplicates (Decision 1A), with tests. This does not touch execution, and it closes a gap that exists today (G15 in [STATUS.md](STATUS.md)).
2. Carry the project path in the request and check it in admission (2A), with tests. No behaviour changes for `noop`.
3. Add the read-only check as a wrapper around an adapter, with tests that use small test children.
4. Add `inspect` and register it, with tests, then the documentation and the Windows record.

## After this decision

If the recommendation is accepted, stage 1 starts with the project names. The Windows observations are recorded above. They point to comparing content hashes in Decision 4A (question 6), and they make a limit on project size (question 7) more important. A write adapter and an operating system sandbox (4B) are for a later note.
