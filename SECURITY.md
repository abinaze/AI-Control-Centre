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
