# Design Note: A Read-Only Git State Adapter

**Status: Proposed. Not accepted.** This note decides whether a third read-only adapter should report the state of the git repository of a project, and how it could do that without running git. It takes [PYTHON_SYNTAX_ADAPTER_DESIGN.md](PYTHON_SYNTAX_ADAPTER_DESIGN.md) as its model for how a file that is not trusted is opened and limited. The evidence is from one machine, and the first question, whether the adapter is worth building, is left to the maintainer as open question 1. Nothing in this note is built.

## Problem

`inspect` says whether a `.git` exists at the top of a project, and nothing else about it. A person or a program that is about to act on a project does not know which branch it is on, whether a merge or a rebase is half done, whether another git process holds a lock, or when anything last happened. AIC runs no program of a project, and its principles leave out git automation, so the facts would have to be read from the files that git keeps, and only read.

## Evidence

The numbers marked Windows were observed by the maintainer under Git Bash with Python 3.14.3, with a script that only reads and printed no name of a project, a branch or a remote.

1. **Plain files were enough on every repository in the sample.** Of the 15 directories that are directly below the folder of the repository, 13 had a `.git` directory and 2 had none. In all 13, HEAD was a branch, none was detached, and the commit that it points to was found in a loose ref file in all 13, and not in `packed-refs`. The ref storage was `files` and the object format was `sha1` in all 13. None was a worktree or a submodule.
2. **The files agree with git.** The commit that the files gave for HEAD was the same as the one that `git rev-parse` gave, in 13 of 13 repositories, including the AIC repository.
3. **What the repositories looked like.** None had a merge, rebase, cherry-pick, revert or bisect in progress, and none had an `index.lock`. One had a stash. 8 had one local branch and 5 had six or more. The last change of HEAD, from the reflog, was under a day ago in 4, under a week in 1, under a month in 4 and under a year in 4. This sample is calm, which says little about busy repositories.
4. **On Linux, with the same code and synthetic repositories that git 2.43.0 made.** Every kind below was recognized, and the commit agreed with `git rev-parse` in all 11 that could be compared: loose refs, `packed-refs`, a detached HEAD, a repository with no commit yet, a stash, a merge in progress, a rebase in progress, an `index.lock`, a repository with the object format sha256, a folder with no repository, and a `.git` that is a file. A repository that stores its refs as `reftable` was faked with a directory and a line of configuration, so it tested only the detection.
5. **A failed task fails its goal.** [SNAPSHOT_LIMIT_DESIGN.md](SNAPSHOT_LIMIT_DESIGN.md) records that after one task has failed, its goal is failed, and no task can be created or made ready in it. That matters for what the adapter does when it cannot read a repository.
6. **`.git` holds most of the files of a repository.** In the AIC repository, 3,253 of its 3,618 files were below `.git`. A read-only run takes a snapshot of every file below the project, so a run of a git adapter reads all of them twice, within the limits of the snapshot.

**Not known.** A real `reftable` repository, a real worktree or submodule, a detached HEAD or an operation in progress on a real repository, and a HEAD that is found only in `packed-refs` were not seen on real data. Branch names that are not ASCII, a very long reflog, a network file system, and the versions of git that other people use were not tried. The version of git of the maintainer was not recorded.

## Facts about the code

- Adapters are registered in code, in `execution/adapters.py`, with a target name, a module that runs in a child process, and a description. `inspect` and `pysyntax` are wrapped in `ReadOnlyAdapter`, which takes a snapshot of the project before and after the run, refuses a project over the limits of the snapshot before the start, and reports a change as a failure. `noop` is not wrapped.
- A child is started with the Python that runs AIC, reads a request from standard input through the shared reader in `execution/child_request.py`, and prints one JSON answer. The process adapter keeps a timeout of 60 seconds and an output cap. A grant for the pair of project and target is needed, and is denied by default.
- `inspect_directory` reads directory listings and file status only, and opens no file. `check_directory`, the check of `pysyntax`, opens files, with limits on the size of a file, the number of files and the bytes in all, and it is the model for opening a file that is not trusted.
- Names that come from a project are data. They are escaped with `escape_name` and cut before they are shown.
- The reason of an outcome is stored in the attempt record, and is at most 1000 characters.
- A snapshot stops with an error when a project has more than 20,000 files or 256 MiB in files, and admission refuses such a project before the start.

## Requirements

1. The adapter runs no program, and in particular not git, and it writes nothing, in `.git` or anywhere else.
2. It reads a small and fixed set of files, each with a limit on how much of it is read, and it never follows a pointer that leads out of the project directory.
3. It never reads or shows the configuration of git, a remote, a name or an address of a person, or the message of a commit.
4. It says what it could not read, and does not guess. A repository that it cannot read is not reported as one with no state.
5. Its answer is the same on Windows and on Linux, and is the same for the same files, apart from the time.
6. A repository that has been changed during the run is reported by the read-only check as for any adapter.

## Options

- **A. Do nothing.** `inspect` says whether `.git` exists. Rejected only if the facts are wanted, which is open question 1.
- **B. Run git as a child.** Rejected. It is an external program that a project can influence through its configuration and its hooks, some of its commands write to the repository, and a program that acts as git automation is what AIC leaves out.
- **C. Read the files that git keeps, and only the few that give these facts.** Recommended. The evidence shows that it works and agrees with git on 13 of 13.
- **D. Also report whether the working tree is clean.** Rejected. It needs the index, in several versions with extensions, and a comparison with the files of the working tree, and it can be wrong in ways that are hard to see. If it is ever wanted, it needs its own note.
- **E. Use a library that reads git.** Rejected. AIC has no dependency at run time.
- **F. Read the configuration to find the ref storage.** Rejected. The configuration holds remote addresses and sometimes credentials, and the presence of a `reftable` directory says the same without reading it.

## Recommendation

1. **A target named `gitstate`,** registered in code, in the wrapper of the read-only check, with a grant needed, and with a module that runs in a child as `inspect` does. The wrapper takes a snapshot of the whole project as for the other two, because the guarantee is the same for every adapter, and the cost is bounded by the limits of the snapshot.
2. **The facts.** The branch that HEAD names, or that HEAD is detached, and the first 12 characters of the commit that HEAD points to. The number of local branches, from the ref files and from `packed-refs`. Whether a stash exists. Which of a merge, a cherry-pick, a revert, a bisect or a rebase is in progress, from the files and the directories that git makes for them. Whether `index.lock` exists. The time of the last change of HEAD, as a UTC time, from the last line of the reflog of HEAD.
3. **The files that it reads.** `HEAD`, the ref file that HEAD names, `packed-refs`, the names under `refs/heads`, `refs/stash`, the last line of `logs/HEAD`, and the existence of `MERGE_HEAD`, `CHERRY_PICK_HEAD`, `REVERT_HEAD`, `BISECT_LOG`, `rebase-merge`, `rebase-apply`, `index.lock` and `reftable`. It does not read `config`, `index`, objects, hooks or any other file.
4. **Limits on reading.** At most 4 KiB of `HEAD`, 256 bytes of a ref file, 8 MiB of `packed-refs`, the last 64 KiB of the reflog, and 10,000 names under `refs/heads`. A file that is over its limit is reported as not read, and it is not cut and used.
5. **What it will not read, and what it says.** A project with no `.git` is reported as not a git repository. A `.git` that is a file or a link is reported as not followed. A `reftable` directory is reported as refs stored as reftable. A HEAD that cannot be resolved from the files is reported as no commit yet when the branch has no ref, and as not read in any other case.
6. **The outcome for those cases is `completed`, with the reason saying what was not read,** and not `failed`, so that a question that was asked and could not be answered does not fail the goal of the task (evidence 5). A directory that cannot be read at all is still a failure, as for `inspect`.
7. **The report is one line,** in the style of `inspect`: `git state: branch <name> at <12 characters>; <n> local branches; stash: yes|no; operation in progress: none|<names>; index.lock: yes|no; last HEAD change: <UTC time>`. A branch name is escaped and cut at 120 characters. A detached HEAD is `detached HEAD at <12 characters>`.
8. **The code** is a function that reads a directory and returns a small value, in `execution/git_state.py`, and a child module that uses the shared reader of the request, as the two adapters before it do.

## What it does not do

- It does not say whether the working tree is clean, whether there are changes that are not committed, or whether the branch is ahead or behind a remote.
- It does not read the history, the author, a message, a tag, a remote or the configuration.
- It does not follow a `gitdir` pointer, so it does not read a worktree or a submodule, and it does not read a repository that keeps its refs as `reftable`.
- It does not change anything, and it does not make git do anything.

## Tests the build needs

- **The function.** Each kind of HEAD and ref, from files that the test makes by hand so that the tests need no git: a branch with a loose ref, a branch that is only in `packed-refs`, a detached HEAD, a branch with no commit, and a HEAD that is garbage. The 40 and the 64 character forms of a commit. The count of branches from loose and from packed refs, with a name that is in both counted once. A stash from `refs/stash` and from `packed-refs`. Each operation in progress, and more than one at a time. `index.lock`. The time from the last line of a reflog, including a reflog with one line, an empty one and one with a line that is not in the format. A `.git` that is a file, a link, and missing. A `reftable` directory.
- **The limits.** A file that is exactly at a limit is read and one byte over is not read, for each of the four limits, and a reflog that is larger than the part that is read gives the last line. 10,000 names are counted and 10,001 are reported as not read.
- **What is never read.** A project whose `config`, `index` and objects cannot be opened gives the same answer, and a test that makes `open` fail for those names shows that they are not opened.
- **What is shown.** A branch name with a control code or with 500 characters is escaped and cut, and no remote address, name or message can appear.
- **The adapter.** Registered with the name, with a grant needed, wrapped in the read-only check, and listed by `aic task targets`.
- **The command line,** through `main()` with real registries: a granted project with a repository gives the report and completes, one with none gives the not-a-repository report and completes, and one without a grant is refused with the grant reason.
- **A test with real git,** that is skipped by an early return when git is not installed, and that checks that the commit and the branch agree with `git`, with the limits of the evidence in mind.
- **Mutations.** Each limit off by one, the order of the checks, the escaping and the cut, the count of branches counting a name in both places twice, and the use of the configuration.
- **On Windows.** A step that runs the target on the 15 directories that were measured and expects the same facts as the measurement, and a report of not a git repository for the 2 that have none.

## Risks

- Git can change where it keeps things. It has a `reftable` format for refs, and a repository in that format is not read at all, so the adapter would report that it does not read it. If that becomes the usual format, the adapter would be of little use. This was not checked beyond the detection.
- The sample is of 13 repositories on one machine. It had no real worktree, no detached HEAD, no operation in progress and no HEAD that is only in `packed-refs`, so the code for those was tested only on repositories that were made for the test.
- The report shows the name of a branch and the time of the last change, which are facts that a person may not want in a stored record. They are shown in the reason that is kept in `executions.json`.
- The whole project is snapshotted for a read of a few small files, which can take a long time for a project near the limits.
- The facts can change between the read and the use. The report is a statement of what was true when it was read.

## Open questions

1. **Should it be built at all?** The facts are modest, and nothing else in AIC needs them yet, because no adapter changes a project. Recommendation: yes, because it is small, the evidence says it can be done safely, and it is the first adapter whose normal answer for some projects is that it could not read what it was asked about. It is the maintainer's decision, and building none is a fair answer.
2. **Should a repository that cannot be read give a completed or a failed outcome?** Recommendation: completed, with the reason that says what was not read, so that the goal does not fail.
3. **Should the time of the last change be a UTC time or an age?** Recommendation: a UTC time, because it is the same for the same files and can be tested.
4. **Should the snapshot cover the whole project or only `.git`?** Recommendation: the whole project, as for every adapter, until there is a reason to give one adapter a different guarantee.
5. **Which names may be shown?** Recommendation: the name of the current branch and the number of the others, and no other name.
6. **Should a `gitdir` pointer be followed?** Recommendation: no. It leaves the project directory.
7. **What should the target be called?** Recommendation: `gitstate`.
8. **Should the configuration be read to find the ref storage?** Recommendation: no, as in option F.

## Recommended order

1. Add `execution/git_state.py` with the function, and its tests, made from files by hand.
2. Add the limits and what is never read, with their tests.
3. Add the child module and its tests.
4. Register the target and add the tests of the target and of `aic task run`.
5. Write the documentation, with a Windows step after the maintainer runs the block.
