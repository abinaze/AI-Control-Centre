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

- **The execution boundary does not bind the CLI.** `aic task ready`, `start`, `complete`, and `fail` change task state directly and do not pass through readiness or admission. A task whose parent goal is failed can be moved to `running` from the CLI.
- **Local state is unauthenticated and unprotected.** Project, goal, and task state is stored as plain JSON. Anyone with write access to the data directory can change it. It is not encrypted, signed, or tamper-evident, and there is no access control.
- **Persistence is not crash-safe.** Writes are not atomic and there is no file locking, so a crash or concurrent processes can corrupt or overwrite state.
- **No execution history is recorded.** Only creation and update timestamps exist, so actions cannot yet be audited after the fact.

## Reporting Security Issues

If a security issue is discovered, provide enough information to reproduce and understand the issue without exposing sensitive credentials, tokens, personal information, or other private data.

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
