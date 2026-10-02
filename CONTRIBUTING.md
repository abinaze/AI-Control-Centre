# Contributing

Thank you for contributing to AI Control Centre.

## Development Principles

AI Control Centre is developed incrementally around explicit, deterministic control boundaries.

Changes should be small, reviewable, testable, and consistent with the existing architecture.

Do not introduce unrestricted execution, autonomous loops, external API dependencies, or other capabilities outside the current architectural boundary without an explicit design decision.

## Development Setup

Requires Python 3.11 to 3.14.

```bash
python -m venv .venv
. .venv/Scripts/activate   # Git Bash on Windows; on Linux/macOS use .venv/bin/activate
python -m pip install -e ".[dev]"
```

On Windows, use `python`, not `python3`.

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

Test files are collected when they are named `test_*.py` or `*_test.py`; both patterns are in use.

Tests must not touch real user data. Construct registries with an explicit path under `tmp_path`, or set `AIC_DATA_DIR` to a temporary directory. Running the suite must not create the default data directory.

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

## Working Agreement

These rules keep the project's claims tied to evidence.

- **Do not claim what you did not run.** Report test, build, and repository state only from actual command output.
- **Predictable operations may be bundled.** A sequence whose result you can foresee can run as one script.
- **Uncertain operations stop at the output.** Run it, stop, read the real output, then decide the next step.
- **Start multi-command shell scripts with `set -e`** so a failing step does not let later steps run on bad state.
- **Documentation follows the code.** Describe a capability as implemented only when its code and tests exist. Label everything else planned or research. See [docs/STATUS.md](docs/STATUS.md) for the labels.
- **Update `docs/STATUS.md`** when a change alters behavior, closes a known gap, or opens a new one.
- **Invariants need tests.** When a change relies on an invariant in `docs/STATUS.md`, make sure a test pins it.
