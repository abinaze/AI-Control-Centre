# Security

AI Control Centre is currently designed as a local-first deterministic control platform.

## Current Security Boundary

The current implementation does not provide unrestricted system execution.

The project currently does not include:

- Arbitrary shell or subprocess execution
- Browser automation
- Git or GitHub automation
- External API execution
- LLM-driven autonomous execution
- Unrestricted tool access

Execution currently operates through explicit contracts, readiness checks, execution targets, registered adapters, and outcome recording.

## Known Boundary Gaps

These are current, verified limitations of the security boundary. Details and reproduction steps are in [docs/STATUS.md](docs/STATUS.md).

- **Local state is unauthenticated and unprotected.** Project, goal, task, and execution record state is stored as plain JSON. Anyone with write access to the data directory can change it. It is not encrypted, signed, or tamper-evident, and there is no access control.
- **Concurrent writers are coordinated only between `aic` processes.** Writes are atomic, so a crash or error during a write does not corrupt a state file, a write that fails is reported as an error that names the file, and the CLI holds an exclusive lock on `.aic.lock` in the data directory for each command that writes. The lock is advisory. It does not stop another program, a person editing a file, or a cloud sync tool from changing a state file, and it is not reliable on network file systems, so keep the data directory on a local disk.
- **The run lock is advisory too, and `gone` does not mean that the work stopped.** `aic task run` holds a lock on `runs/<attempt id>.lock` while it runs, so that `aic task running` can say whether its process is alive and `aic task requeue` can refuse a live run. A process of the same user can take or remove the file, and the lock is not reliable on network file systems. When the owner is `gone`, a child that the adapter started can still be running, because a hard kill of `aic` does not stop it (G13). On Windows, a hard kill of a run of `inspect` left the child running for more than 30 seconds in 2 of 5 trials. A run that a person starts with `aic task start` has no owner, and its owner is always `unknown`.
- **Execution history is local and not tamper-evident.** Each attempt is recorded in `executions.json` with its start, its end, its outcome, and a free-text reason. Reasons are stored as given, including adapter error messages and the reasons a person types for `aic task requeue`, `aic task close-attempt`, `aic task complete` and `aic task fail`, which can contain sensitive details. The file is plain JSON that anyone with write access to the data directory can change. Other status changes are not recorded. `aic task running` reports how long a task has been running from these records, so a start time that was changed by hand changes what it reports. `aic task close-attempt` is a write path outside the normal lifecycle. It writes an end time, the outcome that the task has and a reason into one record, only for a `completed` or `failed` task with exactly one open attempt, and the reason starts with `closed afterwards: `. The end time is the time of the repair and not the time at which the run ended. Anyone who can run the command can write that record, and a person who can edit the file can write anything.
- **The goal archive is local and not tamper-evident either.** `archive.json` holds the goals that were archived, with their tasks, their execution records, the reason that was given and the project directory, as plain JSON, and AIC never deletes it. Anyone who can edit the data directory can edit it, and it is not signed or chained. The execution records in it keep their reasons as they were stored, which for `inspect` include up to three file names from the project, escaped and cut.
- **`aic task run` runs adapter code, and a grant does not limit what that code touches.** `noop` does nothing and runs inside the CLI process. `inspect` is registered as well. It reports what is in a project directory, needs a grant and a registered project, and runs in a child process that never opens a file in the project or follows a link. It is started with `-B`, so it writes no bytecode into the project. The snapshots around it do read every file to hash it. Its reason holds up to three file names from the project, escaped and cut, and is stored in `executions.json` like any reason. `pysyntax` is registered too. Unlike `inspect` it reads the content of every Python file in the project, which makes it the first adapter that reads the content of a person's files on purpose. Its child compiles the source and throws the result away, so nothing is imported, run or written, but it is not a sandbox: the Python compiler handles text from the project, and a crash of the interpreter on source that was built to cause one was not observed and was not tried. It opens a file without blocking and without following a link and checks that the open descriptor is a regular file, it skips virtual environments, and it stops at fixed limits: a file of more than 1 MiB is not read, and more than 10,000 files or 64 MiB read fails the run. Its reason holds up to three file names and error texts from the project, escaped and cut. It needs a grant of its own, and a grant for `inspect` does not cover it. Adapters are registered in code and are never loaded by name from configuration. An in-process adapter that hangs would hang the command, and one that crashes the process would leave the task `running` with its attempt open, which `aic task requeue` recovers. `ProcessAdapter` exists for adapters that must run out of process. It runs a fixed command with a timeout, an output cap and a minimal environment, and stops the whole process tree on a timeout or an interrupt. `inspect` and `pysyntax` are registered as one. A target that acts on a project's files is refused unless its project is registered and its directory exists, and the directory reaches a child process only in the JSON on its standard input. That is information and not a limit on what the child can touch. A wrapper can check that a run left the project as it was, by comparing a snapshot before and after. That detects a change and does not prevent it, it sees only the project, and it is not a sandbox. `inspect` and `pysyntax` are wrapped in it. It cannot stop processes that outlive AIC if AIC is killed hard, and CPU and memory limits are not enforced. A failure reason can include text from the child's standard error. A request for a target that needs a grant is refused unless an active grant in `permissions.json` covers its project and the target. `aic permission grant` makes a grant, and it asks for no confirmation, because the CLI cannot tell a person from a program and a piped answer would satisfy a prompt. A `permissions.json` that cannot be read stops the run, the grant commands and the listing with an error, and it never counts as a grant. The file is plain local text, so anyone who can write to the data directory can add a grant by hand, and `aic validate` does not detect that. A grant says which projects may use a target. It does not limit what the target touches. A grant is a policy for what automation may run. It does not protect against a hostile process that runs as the same operating system user, because the CLI cannot tell who is typing. See [docs/PERMISSIONS_DESIGN.md](docs/PERMISSIONS_DESIGN.md).

## Reporting Security Issues

Please report a security issue privately. Use the "Report a vulnerability" button on the Security tab of the repository, at https://github.com/abinaze/AI-Control-Centre/security. Do not open a public issue or pull request that describes the problem. If the button is not shown, open a public issue that asks for a private way to reach the maintainer and says nothing about the problem itself.

This is a single-maintainer project, so there is no promised response time.

Provide enough information to reproduce and understand the issue without exposing sensitive credentials, tokens, personal information, or other private data.

Security reports should include:

- A clear description of the issue
- The affected component or boundary
- Reproduction steps when available
- Expected behavior
- Observed behavior
- Relevant logs or test output with sensitive information removed

## Security Development Principles

Security-sensitive changes should preserve deterministic behavior and explicit boundaries.

New execution capabilities should not bypass readiness, admission, execution, or outcome boundaries.

Changes that expand execution authority should be introduced only with explicit contracts, tests, validation, and appropriate isolation.
