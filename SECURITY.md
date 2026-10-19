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
- **Concurrent writers are coordinated only between `aic` processes.** Writes are atomic, so a crash or error during a write does not corrupt a state file, and the CLI holds an exclusive lock on `.aic.lock` in the data directory for each command that writes. The lock is advisory. It does not stop another program, a person editing a file, or a cloud sync tool from changing a state file, and it is not reliable on network file systems, so keep the data directory on a local disk.
- **Execution history is local and not tamper-evident.** Each attempt is recorded in `executions.json` with its start, its end, its outcome, and a free-text reason. Reasons are stored as given, including adapter error messages and the reasons a person types for `aic task requeue`, `aic task complete` and `aic task fail`, which can contain sensitive details. The file is plain JSON that anyone with write access to the data directory can change. Other status changes are not recorded.
- **`aic task run` runs adapter code, and a grant does not limit what that code touches.** The only registered adapter is `noop`, which does nothing and runs inside the CLI process. Adapters are registered in code and are never loaded by name from configuration. An in-process adapter that hangs would hang the command, and one that crashes the process would leave the task `running` with its attempt open, which `aic task requeue` recovers. `ProcessAdapter` exists for adapters that must run out of process. It runs a fixed command with a timeout, an output cap and a minimal environment, and stops the whole process tree on a timeout or an interrupt. Nothing registers one yet. It cannot stop processes that outlive AIC if AIC is killed hard, and CPU and memory limits are not enforced. A failure reason can include text from the child's standard error. A request for a target that needs a grant is refused unless an active grant in `permissions.json` covers its project and the target. `aic permission grant` makes a grant, and it asks for no confirmation, because the CLI cannot tell a person from a program and a piped answer would satisfy a prompt. A `permissions.json` that cannot be read stops the run, the grant commands and the listing with an error, and it never counts as a grant. The file is plain local text, so anyone who can write to the data directory can add a grant by hand, and `aic validate` does not detect that. A grant says which projects may use a target. It does not limit what the target touches. A grant is a policy for what automation may run. It does not protect against a hostile process that runs as the same operating system user, because the CLI cannot tell who is typing. See [docs/PERMISSIONS_DESIGN.md](docs/PERMISSIONS_DESIGN.md).

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
