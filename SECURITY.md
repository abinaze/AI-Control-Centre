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
