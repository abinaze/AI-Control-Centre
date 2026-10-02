## Summary

<!-- What does this change do, and why? -->

## Type of change

- [ ] Feature
- [ ] Fix
- [ ] Refactor
- [ ] Documentation
- [ ] Other

## Architectural boundaries

- [ ] Preserves the separation between readiness, admission, starting, execution, and outcome recording
- [ ] Introduces no unrestricted execution, autonomous loop, or external API dependency without a recorded design decision
- [ ] Does not silently repair or rewrite persisted state outside an explicit operation

## Verification

Paste real output. Do not summarize from memory.

- [ ] `python -m pytest -q`
- [ ] `python -m compileall -q src`
- [ ] `git diff --check`
- [ ] Staged diff inspected before committing

## Documentation

- [ ] `docs/STATUS.md` updated if behavior changed or a known gap was opened or closed
- [ ] Anything not yet implemented is labeled planned or research, not implemented
