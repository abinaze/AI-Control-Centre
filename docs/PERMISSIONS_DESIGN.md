# Design Note: Permissions

**Status: Stages 1 and 2 are built; the commands and the documentation stage are not.** The six decisions below were accepted as recommended. Stage 1, the check in admission, and stage 2, the grant registry and its validation, are built, and what happened is at the end of this note. The `aic permission` commands are not built, so nothing can be granted from the CLI yet. It is the third design note of Phase 3 in [ROADMAP.md](../ROADMAP.md), after [COORDINATOR_CLI_DESIGN.md](COORDINATOR_CLI_DESIGN.md) and [PROCESS_ADAPTERS_DESIGN.md](PROCESS_ADAPTERS_DESIGN.md). It covers which projects may use which execution targets, where that is enforced, and what it cannot protect against. No real adapter should be built before this is settled.

## Problem

The only registered target is `noop`, which does nothing. The next adapter will do something, and a ready task can then start it. Today nothing says which tasks may use which target.

This was checked on the current code (Linux sandbox). Two projects were registered, each with a goal and a ready task. `aic task run --target noop` completed both. Admission, `ExecutionAdmission.evaluate`, looks at whether the task is ready and at nothing else. It never looks at the target or the project. With an adapter that does real work, any ready task in any project could run it.

The control principle is that AI proposes and AIC controls. A task can come from anyone, so what automation may run has to be decided by a person, before the run, and recorded.

There is a limit that the note has to state plainly. The CLI cannot tell who is typing. A confirmation prompt was tested: a program that pipes the answer to the prompt confirms it, and only a program with no standard input at all is refused (`EOFError`). A check that a terminal is attached would stop a careless script but not a deliberate one, and it may not work in Git Bash, where Python can see a pipe instead of a terminal. So permissions here are a policy for what automation runs, and a record of who allowed it. They are not a defence against a hostile process that runs as the same operating system user and can run `aic` itself.

## Facts about the current code

- A goal names its project, a project is found by name (`ProjectRegistry.get_project`), and a task belongs to a goal. A task's project is therefore reachable. `aic goal create` refuses an unregistered project, and `aic validate` reports a goal that points at one.
- The coordinator resolves the adapter for a target before it starts anything, and an unknown target is refused without touching state.
- `ExecutionStarter.start` runs admission and then writes, inside one entry of the state guard. A check made in admission therefore sees the same state that the start then changes.
- `ExecutionRequest` is a frozen record with a task ID and a target.
- An adapter is any object with `execute`. It can carry other attributes, as `noop` carries a description.
- State is held in versioned JSON files under the state lock: projects, goals, tasks and executions. A refused request or command changes nothing (INV-1, INV-18).

## Requirements

1. A target that does real work cannot run for a project until a person has allowed it. Absence of a grant means no.
2. The check happens before an attempt opens, in the same critical section as the start, so a refusal writes nothing and a grant cannot change between the check and the start.
3. A grant is recorded with when it was made and why, and keeps its history when it is revoked.
4. The check cannot be skipped by a caller that builds a request itself. The safe default is to require a grant.
5. `aic validate` can find a grant that refers to something that no longer exists.
6. The notes and the documents do not claim more than this gives. They say it is a policy, not a defence against a process with the same operating system rights.
7. Standard library only, Windows and Linux.

## Decisions

### Decision 1: What is permitted

**Option 1A: a grant per project and target.** "Project `alpha` may use target `shell`." Nothing is allowed until granted. A target can declare that it needs no grant, which `noop` does, because it does nothing.

**Option 1B: an approval per task.** A person approves every run. The strongest control and the heaviest. It makes automation a series of confirmations. It can be added later on top of 1A.

**Option 1C: a switch per target, for all projects.** Simple, and too coarse. Allowing a target for one project would allow it everywhere.

**Option 1D: each adapter decides for itself.** A check that every adapter has to remember to make. Rejected: a new adapter would be unsafe by default.

**Recommendation: 1A.**

### Decision 2: Where grants are kept

**Option 2A: a state file, `permissions.json`.** Versioned like the others, written under the state lock, shown by commands, and checked by `aic validate`. It is the fifth state file, and it needs a schema version, a registry, validation and tests.

**Option 2B: a fixed policy in code.** A grant is a commit. Nothing to validate, and a person has to change the code to allow anything. Too rigid for a local tool.

**Option 2C: environment variables or a settings file.** Easy to change and easy to get wrong silently. Rejected.

**Recommendation: 2A.**

### Decision 3: Where the check is made

In admission, which already runs inside the start. The coordinator reads whether the resolved adapter needs a grant, from an attribute on the adapter that defaults to "yes", and sets it on the request. `ExecutionRequest` gains a field, `requires_grant`, which also defaults to "yes", so a caller that builds a request by hand is checked. Admission then finds the task's goal and project and asks whether an active grant exists. A task whose project is not registered is refused.

The refusal reads `target X is not granted for project Y`, changes nothing, and is reported as `rejected` by `aic task run`.

**Recommendation: as described.**

### Decision 4: Who may grant

**Option 4A: plain commands with a required reason.** `aic permission grant <project> --target <name> --reason "<text>"`, `revoke` and `list`. The grant records when it was made and why. The documents say what this does not protect against.

**Option 4B: a confirmation prompt.** Friction only, as tested above. It can annoy a person and it does not stop a program, so it would suggest a protection that is not there. Rejected.

**Option 4C: separation by the operating system.** Keep the state files where only another account can write them. This is the only real separation and it is outside what AIC does.

**Recommendation: 4A.** Any later integration that lets an AI propose tasks must not expose the `permission` commands to it. That belongs to that integration's design.

### Decision 5: The record

Each grant has an `id`, a `project`, a `target`, `granted_at`, a `reason` and `revoked_at`. A grant is active while `revoked_at` is empty. Revoking sets it and deletes nothing, so the history stays. Granting something that is already active is refused. Granting needs a registered project and a registered target, so a typo is caught when it is made. `aic validate` reports a grant for a project that is not registered, a repeated ID, and an active duplicate. A grant for a target that the code no longer registers is reported too.

**Recommendation: as described.**

### Decision 6: What a grant does not cover

A grant says that a target may run for a project. It does not say what the adapter may touch. How an adapter learns a project path, which directory it runs in, and what it may reach are decisions for the note on the first real adapter. A revoke stops later runs and does not stop a run that has already started. Limits stay set per target in code.

## Recommended order

1. **The request field and the check**, library only: `requires_grant` on `ExecutionRequest`, the adapter attribute, and admission asking a grant source. A grant source that holds grants in memory is enough for the tests.
2. **The registry**: `permissions.json`, its schema version, its model and registry, and `aic validate`.
3. **The CLI**: `aic permission grant`, `revoke` and `list`, and `aic task targets` showing which targets need a grant.
4. **Documentation**, including a new invariant, and the limit stated in the security policy.

Tests:

- A target that needs a grant is refused for a project with none, nothing is written, and the reason names the target and the project.
- With an active grant the run goes ahead. After a revoke it is refused again. A grant for one project does not allow another.
- A request built by hand with no `requires_grant` is checked. `noop`, which says it needs none, runs without a grant.
- A task whose project is not registered is refused.
- A grant cannot change between the check and the start: the check and the start share one guard entry.
- The registry round trips, keeps revoked grants, and refuses an active duplicate and an unregistered project or target.
- `aic validate` reports each problem above and passes on a clean state.
- The classification test covers `permission grant` and `revoke` as locking and `list` as read-only.
- Eight `aic task run` processes with a grant in place all complete.

## Risks

- **It cannot tell a person from a program.** Stated above and to be repeated in the security policy.
- **A fifth state file.** More to keep consistent, validated and documented.
- **Deny by default can be tiresome.** Only targets that do real work need a grant, and a grant is one command.
- **A revoke does not stop a run in progress.** It affects the next run.
- **A target that is renamed in code leaves its grants pointing at nothing.** `aic validate` reports them.
- **Time-limited grants, roles and users are not covered.** They would need an identity that does not exist yet.

## Open questions for the maintainer

1. Grants per project and target, deny by default, with `noop` exempt (Option 1A)? Recommendation: yes.
2. Keep them in a versioned `permissions.json` (Option 2A)? Recommendation: yes.
3. Check in admission, with `requires_grant` on the request defaulting to "yes" (Decision 3)? Recommendation: yes.
4. Plain commands with a required reason and no confirmation prompt, and a plain statement of the limit (Option 4A)? Recommendation: yes.
5. Keep revoked grants as history (Decision 5)? Recommendation: yes.
6. Leave what an adapter may touch to the note on the first real adapter (Decision 6)? Recommendation: yes.

## Stage 1: built

Everything in this section was observed on Linux.

- `ExecutionRequest` has a `requires_grant` field that defaults to true. An adapter can declare `requires_grant`, and an adapter that says nothing is treated as needing a grant. `noop` declares false. `ProcessAdapter` takes it as a parameter and defaults to true.
- The coordinator marks the request that it gives to the starter from the adapter, and ignores what the caller put in the field. The adapter itself still receives the request exactly as the caller sent it. An existing test showed the adapter receiving the marked copy, which was a needless change, so only the starter sees the copy.
- `execution/grants.py` holds `GrantSource`, a protocol with one method, `is_granted(project, target)`, and `NoGrants`, the default, which allows nothing. Admission asks the source after the readiness checks. A refusal reads `target X is not granted for project Y`, opens no attempt and leaves the task as it was.
- Admission runs inside the start, so the check and the start share one entry of the state guard.
- Existing tests that run requests without a grant now say so: a `request_for` helper that builds a request with `requires_grant=False`, `requires_grant = False` on the test adapters, and `requires_grant=False` on the process adapters in the CLI tests. That is about fifty call sites in nine files. They were changed before the check was turned on.
- On the real CLI, through a harness that registers a process adapter as `shell`, `aic task run --target shell` printed `Result: rejected` and `Reason: target shell is not granted for project proj`, exited 1, left the task `ready` and wrote no `executions.json`. `--target noop` still completed.
- The suite grew from 480 to 501 tests. Twelve changes made one at a time were each caught by a test: the field defaulting to false, the check skipped, the project and target swapped, `NoGrants` allowing everything, a refusal that does not name the project, the coordinator never or always asking for a grant, the coordinator trusting the caller, an adapter that says nothing treated as exempt, the adapter receiving the marked copy, `noop` needing a grant, and a process adapter exempt by default.
- At the end of stage 1 the grant registry, `permissions.json`, the `aic permission` commands and the checks in `aic validate` were not built, so nothing could be granted and any target that needs a grant was refused. Only `noop` is registered, and it needs none, so the CLI behaved as before. Stage 2 below builds the registry and the validation.

## Stage 2: built

Everything in this section was observed on Linux.

- `permissions/model.py` holds `Grant`: `id`, `project`, `target`, `granted_at`, `reason` and `revoked_at`. A grant is active while `revoked_at` is empty. It refuses a blank field and refuses to be revoked twice, and `Grant.create` strips the names and the reason.
- `permissions/registry.py` holds `PermissionRegistry`. It keeps grants in `permissions.json` next to the task file (`beside`), in the shared versioned format under the key `permissions`, with atomic writes. It has `grant`, `revoke`, `is_granted` and `list_grants`, which leaves revoked grants out unless asked. A missing file means no grants, and reading never creates it. A file that cannot be read, or that holds a damaged grant, is an error and not an empty answer, so a damaged file cannot allow anything.
- The registry refuses a blank project, target or reason, a grant for a pair that already has an active one, and a revoke when nothing is active. A revoked pair can be granted again, and the revoked grant stays as history. A revoke ends every active grant for the pair, so a file edited by hand into holding two cannot leave one behind.
- Deviation from the order above: the rules listed for a grant included a registered project and a registered target. The registry does not check them. Like `create_goal`, which leaves the project check to its command, the registry leaves both checks to its caller, so it needs neither the project registry nor the adapter table. `aic permission grant`, in stage 3, will make both checks. Until then nothing checks them when a grant is made. A grant is compared only with the project of a task and the target of a request, so a grant with a typo never matches, and `aic validate` reports it.
- `GoalTaskValidator` takes an optional `permission_registry` and an optional list of `known_targets`. It reports a repeated grant ID, an active grant that repeats the pair of another, and an active grant for a project that is not registered or a target that the code does not register. A revoked grant is history and is checked only for its ID. Each check applies only when its input is given. `aic validate` passes the registry and the targets from `build_adapter_registry()`, and it still never writes.
- `aic task run` builds its starter with `ExecutionAdmission(grants=PermissionRegistry.beside(...))`. A target that needs a grant now runs when an active grant covers the project and the target, and is refused again after a revoke. A `permissions.json` that cannot be read stops the run with an error before anything is written. `noop` is unaffected.
- On the real CLI, through a harness that registers a target named `shell` that needs a grant, `aic task run --target shell` was refused with no grant: exit 1, the task still `ready`, and no `executions.json` or `permissions.json` written. After a grant made through the registry it printed `Result: completed`. After a revoke it was refused again. `--target noop` completed throughout. `aic validate` reported the grant for `shell` as a grant for an unregistered target, because the real CLI does not register one.
- Eight `aic task run` processes at once, each running a target that needs a grant, all exited 0, all eight tasks ended `completed`, and all eight records were closed.
- The suite grew from 501 to 568 tests: 15 for the model, 25 for the registry, 14 for the validation, 5 for `aic validate` and 8 for `aic task run`. Twenty-four changes made one at a time were each caught by a test: `is_granted` ignoring revocation, the target or the project, or always true; a duplicate grant allowed; a revoke that stops at the first grant, or that is silent when nothing is granted; a listing that shows revoked grants; revoked grants dropped when saving; a damaged grant skipped; names not stripped; a blank reason allowed; a second revoke allowed; the validator checking revoked grants, or missing a repeated ID, an active duplicate, an unregistered project or an unregistered target, or never running the grant check; `aic validate` not passing the targets or the registry; and `aic task run` ignoring the registry, granting everything, or reading another file.
- Not built: the `aic permission grant`, `revoke` and `list` commands, `aic task targets` showing which targets need a grant, the new invariants and the README commands. Until the commands exist a grant can be made only through the library, so nothing can be granted from the CLI and any target that needs a grant is refused. Only `noop` is registered, and it needs none, so the CLI behaves as before.

## After this decision

Stage 3, the CLI, is next. If a different option is chosen anywhere above, this note is revised and approved again before any further code.
