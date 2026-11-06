# Design Note: The Python Syntax Check Adapter

**Status: Accepted as recommended, and built.** This note decides how the second execution adapter, a Python syntax check, reads a project, what it reports, where it stops, and how it is registered. It is item 5B of [FIRST_ADAPTER_DESIGN.md](FIRST_ADAPTER_DESIGN.md), which called it a good second adapter. The evidence was observed on Linux with Python 3.12.3, and none of it was run on Windows. The maintainer pushed the note and told the work to continue, and the eight recommendations were taken as accepted. All five steps of the recommended order are built, and the record of each is in the last sections.

## Problem

`inspect` never opens a file. A syntax check has to open every Python file in a project and hand its content to the Python parser. That is the first time that AIC code reads the content of a person's files on purpose, so four questions come before any code: how a file is opened without being trusted, what is done with its content, how much is read, and what a person is told. One more question came up while looking at the existing adapter. The `inspect` child can fail its own read-only check, and a second adapter built the same way would fail in the same way.

## Evidence

All of this was run on Linux, with Python 3.12.3, the real code and temporary directories.

1. **Compiling to a file writes into the project.** `py_compile.compile` on a file in a temporary directory created `__pycache__/a.cpython-312.pyc` beside it. `ast.parse` and `compile(..., "exec", dont_inherit=True)` on the same file wrote nothing. The read-only wrapper would report the first as a change to the project.
2. **`compile` finds more than `ast.parse`, at the same cost.** Of six faulty constructs, `ast.parse` rejected one, an assignment to a literal. `compile` rejected all six. The five that only `compile` rejected were `return` outside a function, `nonlocal` at module level, `break` outside a loop, a duplicate argument name, and `await` outside a function. Over 574 files of the standard library, `ast.parse` took 1.19 seconds and `compile` took 1.20 seconds, and neither rejected a file. Neither runs the code.
3. **A parser fails in several ways, not one.** On bytes, a null byte, text that is not valid UTF-8, an unknown encoding comment, a Python 2 `print`, a character that is not allowed, an unterminated string and mixed tabs all raised `SyntaxError` (`TabError` for the tabs). 20,000 minus signs in a row raised `MemoryError`, and a sum of 200,000 terms and one line of 100,000 terms raised `RecursionError`. The error had no line number for the null byte, the `MemoryError` and the `RecursionError`, and line 0 for the unknown encoding. A file with a UTF-8 byte order mark and one with a Latin-1 encoding comment parsed. A UTF-16 file was reported as containing null bytes. The text of an error can hold a character from the source, as in the message for a euro sign, which names the character and its code point U+20AC, so it is data from the project.
4. **Opening a file that is not a regular file can block.** A named pipe called `pipe.py` was opened with a plain `open()` in a child process, and the child was still blocked after 3 seconds, when it was killed, because the open waits for a writer. `lstat` said that the entry was not a regular file. Opening with `O_NONBLOCK` and `O_NOFOLLOW` returned at once, and `fstat` on the descriptor said that it was not a regular file. Opening a link called `link.py` with `O_NOFOLLOW` was refused with error 40. When a regular file was replaced by a pipe after `lstat` had looked at it, `lstat` had said regular and `fstat` on the descriptor said not regular, so only the check on the open descriptor sees the swap. `O_NOFOLLOW` and `O_NONBLOCK` exist on Linux and were not looked at on Windows.
5. **What a walk and a parse cost.** The standard library had 572 `.py` files, 10.1 MiB, and took 1.48 seconds to read and parse, 1.28 of them in the parser. The largest file was 787 KiB. A fresh virtual environment that held only `pip` and `pytest` had 983 `.py` files, 12.4 MiB, took 2.73 seconds, and its largest file was 219 KiB. Neither had a file that failed to parse. The AIC repository has 129 `.py` files out of 157 tracked files. A virtual environment inside a project therefore adds more files than a small project has.
6. **The grammar is that of the Python that runs.** With `feature_version`, `type X = int` and a generic function were rejected as 3.11, `match` and `except*` were rejected as 3.9, and an assignment expression was rejected as 3.7. A nested f-string that reuses its quotes, which is valid only from Python 3.12, was accepted as 3.7 as well. The documentation says `feature_version` is best effort, and this shows it. A check that names the version it ran with is honest, and one that pretends to check for another version is not. Only Python 3.12 was available, so how 3.11 and 3.14 behave was not observed.
7. **The `inspect` child can fail its own read-only check (new gap, G22).** `aic` was installed in editable mode from a copy of the AIC source, and that copy was registered as a project. A run of `inspect` on it failed with `the project changed during a read-only run: 0 changed, 1 added, 0 removed (src/aic_control_centre/execution/__pycache__/inspect_project.cpython-312.pyc)`, because the child imported its own module for the first time and Python wrote the bytecode. After the bytecode existed, the same run completed. After the source of the child was edited, the next run failed again with `1 changed`, and the run after that completed. Running the child by hand with `python -B` left no bytecode, and without `-B` it wrote one. The child's environment list does not pass `PYTHONDONTWRITEBYTECODE`. This is a false failure and it is safe, but a person who registers the AIC repository as a project meets it. It was seen through the real CLI on Linux and not on Windows.

## Facts about the current code

- `build_inspect_adapter` wraps a `ProcessAdapter` that runs `[sys.executable, "-m", "aic_control_centre.execution.inspect_project"]` with `requires_grant=True` and `requires_project=True` in a `ReadOnlyAdapter`. The process adapter stops a child after 60 seconds, limits its output, and keeps a reason to 1000 characters.
- The snapshot compares the kind, size, modification time in nanoseconds and SHA-256 of every name, and never opens anything that is not a regular file. It does not compare access times, so reading a file is not a change.
- `inspect_project.py` is both a library and a child. It walks with directory listings and file status, never follows a link, and counts a Windows junction as a link by its reparse tag. `describe` escapes names and cuts them at 60 characters.
- `run` in `inspect_project.py` decodes the request as UTF-8, parses the JSON, takes `project_path`, and answers a failed outcome for each fault, with the directory check from `projects/directory.py`. Nothing else shares that code.
- Three tests depend on what ships. `test_the_shipped_registry_holds_inspect_and_noop` compares the sorted list of targets, and `test_targets_lists_inspect_and_what_it_needs` expects `Execution targets: 2`, so registering a third adapter changes both of them. `test_inspect_is_a_read_only_process_that_needs_a_grant` compares the exact command of the child, so adding `-B` changes it. `test_every_shipped_adapter_except_noop_needs_a_grant` already covers any adapter that is added, and the tests that make their own registry are not affected.

## Requirements

1. The check never imports, runs or writes any project file, and never reads outside the project.
2. A file that is not a regular file is never opened, even if it was a regular file a moment before.
3. The result is the same for the same project, whatever order the system lists the files in.
4. Everything from the project that is shown, a name or the text of an error, is escaped and cut.
5. Every fault is a recorded outcome and never a crash, whatever the parser raises.
6. A person can tell from the reason which Python judged the files, what was checked and what was not.
7. Grants, the project check and the read-only wrapper apply as they are. Standard library only, on Windows and Linux.
8. Existing adapters, commands and tests keep working.

## Options

### Decision 1: the child must not write bytecode (G22)

**1A. Add `-B` to the fixed command of the `inspect` child and use it for the new child too (recommended).** The flag is part of the command that AIC ships. Nothing from a task reaches it.

- Pro: it removes the cause for both adapters, and the read-only check stays as strict as it was.
- Con: the child starts a little slower, because it never uses a stored bytecode file for AIC's own modules. This was not measured.
- Limit: the parent process runs the wrapper. A lazy import in the parent during a run would write bytecode in the same way. The parent was not seen to do it, and it was not tried.

**1B. Leave it and document it.** A person would have to know not to register the tree that AIC is installed from. Rejected: a false failure with no cause that a person can see.

**1C. Pass `PYTHONDONTWRITEBYTECODE` to the child.** It adds a variable to a list of names that has been fixed so far, and a flag in the command does the same work. Rejected.

**1D. Leave `__pycache__` out of the snapshot.** It would hide a real write by the child. Rejected.

### Decision 2: what is done with a file

**2A. `compile(data, "<file>", "exec", dont_inherit=True)`, with the result thrown away (recommended).** It runs nothing, writes nothing (evidence 1 and 2), and finds five kinds of error that `ast.parse` misses at the same cost. The file name given to it is a fixed text, so that no project text is used to build anything.

**2B. `ast.parse`.** The same cost and fewer errors found, so a project with `return` outside a function would pass a syntax check. Rejected.

**2C. `py_compile` or `compileall`.** They write into the project. Rejected on evidence 1.

**2D. Import the module.** It runs the code of the project. Rejected without discussion.

### Decision 3: which files and how they are read

**3A. Regular files with the extension `.py`, found with the same kind of walk as `inspect`, and opened with `O_NONBLOCK` and `O_NOFOLLOW` where the system has them, and then checked with `fstat` on the open descriptor (recommended).** A link is counted and never followed. An entry whose descriptor is not a regular file is skipped and counted. The file is read from the descriptor, up to one byte more than the size limit, so a file that grew is not read whole. The names are sorted, so the order of the listing does not matter.

- Where the flags do not exist, on Windows, the status check from the walk is all there is, and a junction is a link by its reparse tag. That was not observed for this adapter.

**3B. Check with `lstat` and then open by name.** It is open to the swap of evidence 4. Rejected.

**3C. Include `.pyi`, `.pyw` and scripts without an extension.** A stub file is valid syntax, and a script is found only by reading it. Not now. A person who wants them can ask for them later.

### Decision 4: which directories are not walked

**4A. A fixed list of names, and any directory that has a `pyvenv.cfg` at its top (recommended).** The names are `.git`, `__pycache__`, `node_modules`, `.tox`, `.nox`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache` and `.eggs`. A virtual environment is recognised by its file and not by its name, so `env` and `myenv` are skipped as well as `.venv`. The count of directories that were skipped is in the reason, so nothing is skipped quietly.

- Pro: a virtual environment is the other people's code and it is larger than most projects (evidence 5).
- Con: a project that keeps its own Python code in a directory with one of these names is not checked. The reason says that directories were skipped.

**4B. Skip nothing.** A person who has a virtual environment in the project gets a check of every package in it. Rejected.

**4C. Skip only `.venv` and `venv`.** It misses any other name. Rejected.

### Decision 5: limits, and what a limit means

The process adapter stops a child after 60 seconds, and a stop gives a failed outcome with no facts. A limit that AIC sets itself gives a reason. It has to be a number and not a clock, so that the same project always gives the same answer.

**5A. A file of more than 1 MiB is not read and is counted. More than 10,000 `.py` files, or more than 64 MiB read, stops the check with a failed outcome that says which limit was passed (recommended).** The largest file of the standard library was 787 KiB. At the speed seen, about 8 MiB a second on Linux, 64 MiB is about 8 seconds, which is an estimate and not a measurement, and nothing was measured on Windows. All three numbers are guesses, as the project size limit was in the first note, and they are named constants so that a later note can change them with evidence.

- A file that is too large is a fact about one file, so the outcome can still be `completed`, and the reason says how many were not read. A limit on the whole check means that the answer would be about an unknown part of the project, so that is `failed`.

**5B. Stop at a time limit inside the child.** The answer then depends on the speed of the machine. Rejected.

**5C. No limits and rely on the 60 seconds.** A big project would end as a timeout with no facts. Rejected.

### Decision 6: which grammar

**6A. The grammar of the Python that runs AIC, and the reason names its version (recommended).** A project that is written for a newer Python than the one that runs AIC fails, and the version in the reason says why.

**6B. A target version with `feature_version`.** It does not do what it says (evidence 6). Rejected.

**6C. Find the project's Python and run that.** It needs a second interpreter, which is a new thing to trust and to find. Not now.

### Decision 7: what is reported

**7A. One line, as for `inspect`, with the version, the counts and at most three errors in the order of their names (recommended).** An error is the name, the line when the parser gave a real one, and the text of the error, each escaped and cut. The source line that the parser keeps is never used, because it is project text that can hold a secret.

    checked Python syntax with Python 3.12: 41 files checked, 2 with errors, 1 too large, 3 directories skipped; errors: pkg/a.py line 3: invalid syntax; pkg/b.py line 9: unterminated string literal

The example is an illustration of the form, not output. Any error is a failed outcome, so a task whose check found errors ends `failed`, and one that found none ends `completed`. Every exception that a file raises is one error, with the name of the exception where the parser gave no text. The attempt record keeps the reason, so `aic task history` shows it.

**7B. Store a full list of errors in a file.** It needs storage, a retention rule and care with what is in the list. Not now, as in Decision 6 of the first note.

### Decision 8: how it is registered and how the code is shared

**8A. A target called `pysyntax`, built by `build_pysyntax_adapter`, a `ReadOnlyAdapter` around a `ProcessAdapter` that runs `[sys.executable, "-B", "-m", "aic_control_centre.execution.check_python"]`, with a grant and a project required (recommended).** It needs a grant like `inspect`, and `aic task targets` says so.

**8B. Share the reading of the request instead of copying it.** Both children decode UTF-8, parse JSON, take the project path and run the directory check, and each fault has a failed outcome with its own text. The recommendation is to move that into one small function first, with the texts of `inspect` pinned by tests before the move, and then to use it twice. Two copies would drift, and the texts are already tested.

**8C. Add the check to `inspect`.** It would make a read-only report into something that reads every file. Rejected.

## Recommendation

Take 1A, 2A, 3A, 4A, 5A, 6A, 7A and 8A. A run would go like this:

    aic permission grant app --target pysyntax --reason "check the syntax"
    aic task run <task-id> --target pysyntax

    admission:  the project is registered, its path exists, a grant covers it
    run:        snapshot, the child walks and compiles, snapshot
    outcome:    completed with the counts, or failed with the first errors

## What this does not do

- It does not import or run the project, and it does not check types, style or names. A file can compile and still fail when it runs.
- It does not know which Python the project is written for (Decision 6).
- It does not stop a write. The read-only check detects, and it is not a sandbox (G16).
- It does not look at other languages, at stub files, or at scripts without an extension.
- It does not read outside the project, and it does not follow a link.

## Tests the build needs

- The fix: the commands of both children hold `-B`. A read-only run of `inspect` and one of the new adapter on a project that holds the module that the child imports, with no bytecode there and with stale bytecode, completes and leaves no `__pycache__` file. The old command fails the same test with the message of evidence 7.
- The shared reader: every failure text of `inspect` is pinned before the move and unchanged after it, for a request that is not UTF-8, not JSON, with no path, and with a path that is missing, not a directory or unreadable.
- The check: a project of valid files completes, and a file with each of the six constructs of evidence 2 fails. A file with a byte order mark, with an encoding comment, and an empty file pass. A null byte, a file that is not UTF-8, a file with a very deep expression, and a file with a very long expression each give one error and the run goes on. No error shows the source line.
- The walk: a link named `x.py` is not followed and not read. A pipe named `x.py` is skipped and the run does not block, and a file swapped for a pipe after the walk is skipped. Only `.py` files are read. Each directory on the list and a directory with `pyvenv.cfg` are skipped and counted, and a directory that only has a similar name is not skipped.
- The limits: a file just under and just over 1 MiB, a project just under and just over 10,000 files, and one just over 64 MiB read. The first two limits and the third give the outcomes in Decision 5. The result does not depend on the order of the listing, which a test shows by feeding the same entries in two orders.
- The reason: the form of Decision 7, names and error text escaped and cut, at most three errors, in the order of their names, and a length that stays under 1000 characters with the longest names.
- The adapter: it needs a grant, `aic task targets` says so, and a run without one is refused and writes nothing. A run on a project with an error ends `failed`, and one without ends `completed`, through the real CLI. The project is the same before and after.
- On Windows: a project path with spaces and a non-ASCII name, a junction named `x.py` that is not followed, and the full suite with the two skips unchanged.

## Risks

- **A false failure.** A project that is written for a newer Python than the one that runs AIC fails with a message that looks like a real error. The version in the reason is the only help.
- **Cost on Windows is unknown.** Listing a tree took about ten times longer per file on Windows than on Linux. The wrapper also reads every file of the project twice to hash it (G16), so a project with large files that are not Python costs more than the check does.
- **Error text is project text.** The parser can put a character or a name from the source into its message. It is escaped and cut at a short length, and the source line is never used. A message of that length can still hold a short word that a person did not want shown.
- **The numbers are guesses.** The three limits were chosen from one machine and one standard library.
- **A crash of the interpreter.** A parser that crashed the child would show as a failed outcome with an exit status, which the process adapter already records. A crash was not observed, and extremely deep input was tried only up to the sizes in evidence 3.
- **Flags on Windows.** `-B` and the file flags were not looked at on Windows.

## Open questions for the maintainer

Each has a recommendation, and the reply "continue with best" accepts them all.

1. Add `-B` to the `inspect` child, and use it for the new child (Decision 1A)? Recommendation: yes, and record the false failure as G22.
2. Use `compile` and not `ast.parse` (2A)? Recommendation: yes.
3. Skip the listed directories and any directory with a `pyvenv.cfg`, and say how many (4A)? Recommendation: yes.
4. Set the limits at 1 MiB a file, 10,000 files and 64 MiB read (5A)? Recommendation: yes, as named constants, with the Windows cost not yet known.
5. Treat a file that is too large as a count in a completed run, and a limit on the whole check as a failure (5A)? Recommendation: yes.
6. Check `.py` files only (3A and 3C)? Recommendation: yes.
7. Call the target `pysyntax` (8A)? Recommendation: yes.
8. Move the reading of the request into one function before the second child uses it (8B)? Recommendation: yes.

## Recommended order

1. Fix the bytecode write: `-B` for the `inspect` child, with the tests of the fix, and record G22. Built.
2. Move the reading of the request into one function, with the texts of `inspect` pinned first. Built.
3. Add the check as a library, with its tests. Built.
4. Add the child and register `pysyntax`, with the tests of the adapter and the change to the two tests that count the adapters, which comes before the registration. The test that compares the command of the child changes with the fix in step 1. Built.
5. Write the documentation and, after the maintainer runs it, the Windows record. Built.


## Stage 1: the bytecode fix (built)

The `inspect` child is started with `-B`. `build_inspect_adapter` in `execution/adapters.py` now runs `[sys.executable, "-B", "-m", INSPECT_MODULE]`, and its docstring says why. Nothing else in the command changed, and no environment variable was added (Decision 1A, and not the variable of 1C).

There were three commits, in this order. First, `test_inspect_is_a_read_only_process_that_needs_a_grant` stopped comparing the whole command and checks that it starts with the interpreter and ends with `-m` and the module, because a test that compares the whole command cannot pass both before and after the fix. Second, the fix. Third, `tests/unit/test_inspect_bytecode.py` with three tests: `test_the_inspect_child_is_started_without_writing_bytecode`, `test_a_child_that_imports_from_the_project_leaves_no_bytecode` and `test_stale_bytecode_in_the_project_is_left_as_it_was`. The last two take the flags of the real adapter, everything before `-m`, and run a small child that imports a module from the project through the real read-only wrapper.

Linux evidence. Against the old command all three tests fail. The first misses `-B`. The other two end `failed` with the messages of evidence 7: `0 changed, 2 added, 0 removed (lib/__pycache__, lib/__pycache__/helper.cpython-312.pyc)` when no bytecode existed, and `1 changed, 0 added, 0 removed (lib/__pycache__/helper.cpython-312.pyc)` when it was stale. Four mutations of the fix were each caught: removing `-B`, putting it after the module, and using `-O` or `-I` in its place. With the fix, the real CLI completed three runs of `inspect` on a copy of the source that was both the installed tree and the project: a first run with no bytecode for the child, a run after the source of the child was edited, and a repeat. Before the fix the first two failed. No bytecode file for the child was written.

Windows record. The maintainer ran the full suite on Windows under Git Bash before each of the three commits, which gave 1091, 1091 and 1094 passed, each with 2 skipped. The last was on the commit `89599cd`. A run of `aic task run` with the `inspect` target on the AIC directory through the real CLI on Windows was not made, so on Windows `-B` has been exercised by the tests only.

What it does not cover. The parent process that runs `aic` was not seen to write bytecode into a project during a run, and that was not tried. G22 is closed for the child only.


## Stages 2 to 4: the shared reader, the check and the adapter (built)

All four stages that follow the fix are built, in four blocks of commits. The record of each is below, and then what differs from the decisions above, and what is not known.

### Stage 2: the shared reader of the request of a child process

`execution/child_request.py` holds what both children need: decoding the request, finding the project path, asking for the check of the directory, the failed outcome for a request that cannot be done, and printing one JSON line with exit status 0. The reader takes the check of the directory as a parameter, and each child passes its own `directory_problem` when it runs. The three existing tests that replace names in `inspect_project` therefore pass unchanged. Four tests that pin more of what the `inspect` child does with a request were added first and passed on the old code: a path with a NUL character, a long path cut at the path limit, and a message of the system that is escaped and cut or that is missing. The import of the path limit in the tests moved in its own commit before the code did.

Linux evidence. The old and the new child were run as real subprocesses on 20 requests, among them bad UTF-8, JSON nested 200,000 deep, a byte order mark, a NUL path, a lone surrogate and a path of 300 characters, and stdout, stderr and the exit status were identical in every case. 28 mutations of the new module and of the changed child left no survivor. The first round had three: no test showed that the reader returns the path as it was given and not the escaped and cut path, which would make a child walk a shortened path, no test compared the exact line that the child prints, and one mutation of mine was an identity assignment and proved nothing. The first two got tests, and the third was replaced.

Windows record. The maintainer ran the full suite on Windows under Git Bash before each of the five commits, which gave 1098, 1098, 1117, 1117 and 1117 passed, each with 2 skipped. The last was on the commit `5c161a3`.

### Stage 3: the check

`execution/check_python.py` holds the library. `compile_problem` compiles source with the compiler and throws the code object away. `read_python_file` opens a file with the flags for binary mode, no blocking and no following of a link, where the system has them, and checks that the open descriptor is a regular file. `check_directory` walks the project, skips the listed directories and any directory with a `pyvenv.cfg`, and applies the three limits. `describe` writes the reason. The numbers are named constants: 1 MiB for a file, 10,000 files, and 64 MiB read.

Linux evidence. On the standard library of the machine, 572 files were checked with no problem, and 2 symlinked files were counted as not read, as the rule says. A virtual environment named `env` was skipped by its marker file alone. 46 mutations left one survivor, the removal of the binary mode flag, which has no effect on Linux, which has no such flag. The test that reads bytes with `\r\n` and a `\x1a` passed on Windows with the flag present, and the mutation itself was not run on Windows. A test found that a `SyntaxError` with no message was reported as `None`, which was fixed to the name of the type. A mutation that made a fake listing return the same entries for every directory looped for ever, so the fake now returns its entries for the top directory only.

Windows record. The maintainer ran the full suite on Windows under Git Bash before each of the two commits, which gave 1117 and 1169 passed, each with 2 skipped. The last was on the commit `017c957`. The 52 new tests passed on Windows, among them the test with a real directory junction.

### Stage 4: the child and the adapter

`run` and `main` were added to `check_python.py`, so the module is the child as well. `build_pysyntax_adapter` in `execution/adapters.py` returns a `ReadOnlyAdapter` around a `ProcessAdapter` that runs `sys.executable -B -m aic_control_centre.execution.check_python`, with a grant and a project required, and `build_adapter_registry` registers it as `pysyntax`. The two tests that assumed that only `inspect` and `noop` ship were changed first, in their own commit. A grant for `inspect` does not cover `pysyntax`, and a test shows it.

A bug in the library of stage 3 was found while the child was tested, and fixed in its own commit. The compiler emits `SyntaxWarning` for source that is valid, such as an invalid escape sequence or `is` with a literal. The child printed those warnings to its standard error, and under a filter that turns warnings into errors a valid file was reported as a syntax error. The compile step now ignores warnings. The new test fails on the old code with `invalid escape sequence`, and the standard error of the child went from two lines to none.

Linux evidence. 21 mutations of the child and of the registration left no survivor. Through the real CLI: `aic task targets` lists three targets, and `pysyntax` is marked as needing a grant. A clean project completed. A project with two faulty files failed with the first problems in the order of their names, for example `bad.py line 1: invalid syntax; worse.py line 1: 'return' outside function`. A run without a grant was rejected. A run on a copy of the AIC source that was both the installed tree and the project completed with 137 files checked and no problem, and wrote no bytecode for the child, which is the case of G22.

Windows record. The maintainer ran the full suite on Windows under Git Bash before each of the seven commits, which gave 1169, 1169, 1170, 1170, 1181, 1181 and 1196 passed, each with 2 skipped. The last was on the commit `d324f64`. A run of `aic task run` with the `pysyntax` target through the real CLI on Windows was not made.

### What differs from the decisions above

- The reason has a fifth count, `not read`. It counts a link named like a Python file, a pipe or another entry that is not a regular file, a file that could not be opened or read, a directory that could not be listed, and an entry whose status could not be read. The reason is `checked Python syntax with Python 3.12: 41 files checked, 2 with errors, 1 too large, 0 not read, 3 directories skipped; errors: ...`.
- A name and an error text are each cut at 60 characters after escaping, and the escaped text is cut again at 90, so that the longest reason stays under 1000 characters.
- A reason for a check that stopped at a limit is `checked Python syntax with Python 3.12: stopped: too many Python files: more than 10000`, or `too much Python code: more than 64.0 MiB`. A file that is too large counts towards the number of files.
- The directories are not listed in the order of their names. The problems are sorted by name at the end, which is all that the report needs to be the same whatever the order of the listing, and a test shows it.
- The suffix `.py` is compared exactly. The names of the skipped directories and the marker file are compared without regard to case.

### What is not known

- A run of the adapter through the real CLI on Windows was not made. A real pipe and a real link to a file are tested only where the system can make them, and those tests check nothing on Windows.
- Python 3.11 and 3.14 were not observed. The grammar is that of the Python that runs AIC (G23 in [STATUS.md](STATUS.md)).
- The three limits are guesses from one machine, and the cost of a run on Windows was not measured (G24 in [STATUS.md](STATUS.md)).
- A crash of the interpreter on source that was built to cause one was not observed and was not tried. The sizes of nested source that were tried are those of the evidence above.
