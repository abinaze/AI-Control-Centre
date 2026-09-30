# Contributing

Thank you for contributing to AI Control Centre.

## Development Principles

AI Control Centre is developed incrementally around explicit, deterministic control boundaries.

Changes should be small, reviewable, testable, and consistent with the existing architecture.

Do not introduce unrestricted execution, autonomous loops, external API dependencies, or other capabilities outside the current architectural boundary without an explicit design decision.

## Development Workflow

Use the following workflow for changes:

1. Inspect the existing implementation and tests.
2. Identify the smallest change required.
3. Implement the change.
4. Run focused tests for the affected behavior.
5. Run the complete test suite.
6. Run Python compilation checks.
7. Run Git whitespace checks.
8. Inspect the staged diff before committing.
9. Commit the change with a clear, professional commit message.
10. Push the commit and verify that the working tree and branch are clean.

## Testing

Tests should verify observable behavior and important boundary conditions.

Run the complete test suite with:

```bash
python -m pytest -q
```

Run Python compilation checks with:

```bash
python -m compileall -q src
```

Check staged or working-tree whitespace errors with:

```bash
git diff --check
```

## Architecture Changes

Architecture changes should be introduced incrementally.

New boundaries should have explicit contracts and tests before dependent functionality is added.

Lifecycle state should remain deterministic and persisted state should not be silently repaired by unrelated operations.

Execution-related changes must preserve the separation between readiness, admission, starting, execution, and outcome recording.

## Commit Messages

Use concise conventional-style commit messages that describe the actual change.

Examples:

```text
feat: add execution boundary
fix: validate execution outcome identity
refactor: unify execution coordinator result
docs: document execution architecture
```

Avoid commits that mix unrelated architectural changes.
