# AI Control Centre

AI Control Centre is a local-first foundation for building a deterministic AI development and control platform.

The project is being developed incrementally from explicit software boundaries rather than starting with autonomous agents or unrestricted tool execution.

## Current Status

**Development stage:** Alpha

**Current focus:** deterministic task lifecycle, validation, readiness, and execution boundaries.

The verified state of the project, including what is implemented, what is only planned, and the known gaps, is recorded in [docs/STATUS.md](docs/STATUS.md).

The current implementation provides:

- Project registration
- Goal management
- Task management
- Explicit task lifecycle transitions
- Goal lifecycle reconciliation
- Validation of persisted goal and task state
- Task readiness evaluation
- Execution admission, start, and outcome recording, reached through `aic task run`
- Execution target selection and adapter registration; the only adapter is `noop`, which does no work
- Execution coordination, through `aic task run`
- Deterministic local JSON persistence with atomic writes, a schema version, and a lock that keeps concurrent `aic` commands apart

The current implementation does **not** provide:

- Real shell execution
- Browser execution
- Git execution
- GitHub automation
- LLM execution
- Autonomous agent loops
- Unrestricted tool execution
- Any concrete execution adapter

These capabilities are intentionally deferred until the underlying control boundaries are stable and well tested.

### Known gaps

Nothing detects a `running` task whose process has died. A person recovers such a task with `aic task requeue`, which cannot tell whether the process is really gone. `aic task running` shows how long each `running` task has been running, to help a person to decide. This and the missing transition history are tracked as G5 and G4 in [docs/STATUS.md](docs/STATUS.md). Each attempt is recorded and `aic task history` shows it, but an attempt left open for a finished task by a failed write cannot be closed from the CLI (G11).

## Quick Start

Requires Python 3.11 to 3.14.

```bash
python -m venv .venv
. .venv/Scripts/activate   # Git Bash on Windows; on Linux/macOS use .venv/bin/activate
python -m pip install -e ".[dev]"
aic doctor
python -m pytest -q
```

## Command Line

```text
aic doctor                                  Check the local environment
aic validate                                Validate persisted goal and task state

aic project add <path>                      Register a local project (names must be unique)
aic project list                            List registered projects

aic goal create "<description>" --project <name>   (the project must be registered)
aic goal list
aic goal status <goal-id>                   Show a goal (reconciles and saves its status)

aic task create --goal <goal-id> "<title>"
aic task list
aic task status <task-id>
aic task readiness <task-id>                Check whether a task is ready for execution
aic task ready <task-id>                    pending -> ready (parent goal must be open)
aic task start <task-id>                    ready -> running (must pass readiness)
aic task complete <task-id> [--reason "<text>"]   running -> completed
aic task fail <task-id> [--reason "<text>"]       running -> failed
aic task requeue <task-id> --reason "<text>"   running -> ready (recovery; the goal must be open)
aic task history <task-id>                  Show the recorded execution attempts for a task
aic task running [--older-than <duration>]  List the running tasks and how long each has run (30m, 2h, 1d)
aic task run <task-id> --target <name>      Run a ready task through an execution target
aic task targets                            List the execution targets and whether each needs a grant (only noop exists)

aic permission grant <project> --target <name> --reason "<text>"   Let a project use a target that needs a grant
aic permission revoke <project> --target <name>                    Withdraw that permission
aic permission list [--all]                 List the permissions (--all includes revoked ones)
```

Every command except the read-only ones (`doctor` and the `list`, `status`, `readiness`, `history`, `targets` and `running` commands) takes an exclusive lock on the data directory for as long as it runs. `aic task run` is the exception: it takes the lock only while it reads or writes state, not while the adapter runs, so other commands, including `aic task requeue`, still work during a run. Its only target, `noop`, marks a task completed without doing any work, so it proves the path and nothing else. If another `aic` command holds it for more than 10 seconds, the command stops without changing anything and prints `Error: another aic process is using the state files (waited 10s).`

A minimal walkthrough:

```bash
aic project add .
aic goal create "Ship the first release" --project AI-Control-Centre
aic task create --goal <goal-id> "Write the release notes"
aic task ready <task-id>
aic task readiness <task-id>
aic task start <task-id>
aic task complete <task-id>
aic goal status <goal-id>
aic validate
```

## Configuration

Configuration is read from environment variables. A `.env` file is **not** loaded automatically; see `.env.example`.

| Variable | Purpose | Default |
| --- | --- | --- |
| `AIC_DATA_DIR` | Directory for `projects.json`, `goals.json`, `tasks.json`, `executions.json`, `permissions.json`, and the lock file `.aic.lock` | Windows: `%LOCALAPPDATA%\AI-Control-Centre`; otherwise `~/.local/share/ai-control-centre` |
| `AIC_DEFAULT_MODEL_PROVIDER` | Reserved. Read into configuration but not used yet | `local` |

## Design Principles

### Local-first

The foundation is designed to operate locally without requiring external AI services or cloud infrastructure.

### Deterministic

Core lifecycle and control decisions should be explicit, reproducible, and testable.

### Boundary-first

Capabilities are introduced through explicit contracts and boundaries instead of allowing unrelated components to directly mutate project state.

### Explicit lifecycle ownership

Task and goal lifecycle transitions are controlled by the appropriate domain components.

### Execution isolation

Execution targets are resolved through an adapter registry. Execution adapters are separated from lifecycle persistence.

### Incremental architecture

The system is built in small verified milestones. New capabilities should be added only when their architectural boundary is justified.

### Documentation matches the code

A capability is described as implemented only when its code and tests exist. Everything else is labeled planned or research.

## Architecture

The current conceptual flow is:

```text
Project
   |
   v
Goal
   |
   v
Task
   |
   v
Validation
   |
   v
Readiness
   |
   v
Execution Admission
   |
   v
Execution Start
   |
   v
Execution Target
   |
   v
Execution Adapter
   |
   v
Execution Outcome
   |
   v
Task / Goal Lifecycle
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full description.

## Documentation

| Document | Purpose |
| --- | --- |
| [docs/STATUS.md](docs/STATUS.md) | Verified status, known gaps, and invariants |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the system is structured today |
| [docs/DESIGN_DIRECTIONS.md](docs/DESIGN_DIRECTIONS.md) | Research on future directions; not committed |
| [docs/RECOVERY_DESIGN.md](docs/RECOVERY_DESIGN.md) | Design for recovering tasks left in `running`; Option A is implemented as `aic task requeue` |
| [docs/EXECUTION_RECORDS_DESIGN.md](docs/EXECUTION_RECORDS_DESIGN.md) | Design for recording execution attempts; implemented |
| [docs/FILE_LOCKING_DESIGN.md](docs/FILE_LOCKING_DESIGN.md) | Design for locking the state files; implemented |
| [docs/TRANSITION_LOG_DESIGN.md](docs/TRANSITION_LOG_DESIGN.md) | Design note on status history and a transition log; Option A implemented |
| [docs/COORDINATOR_CLI_DESIGN.md](docs/COORDINATOR_CLI_DESIGN.md) | Design note on reaching the execution coordinator from the CLI; implemented |
| [docs/PROCESS_ADAPTERS_DESIGN.md](docs/PROCESS_ADAPTERS_DESIGN.md) | Design note on out-of-process adapters, timeouts and limits; stages 1 and 2 built |
| [docs/PERMISSIONS_DESIGN.md](docs/PERMISSIONS_DESIGN.md) | Design note on which projects may use which execution targets; built |
| [docs/STALE_TASKS_DESIGN.md](docs/STALE_TASKS_DESIGN.md) | Design note on a read-only listing of how long tasks have been `running`; implemented as `aic task running` |
| [docs/FIRST_ADAPTER_DESIGN.md](docs/FIRST_ADAPTER_DESIGN.md) | Design note on the first execution adapter that does real work on a project; accepted, stage 1 built |
| [ROADMAP.md](ROADMAP.md) | Phased plan |
| [CHANGELOG.md](CHANGELOG.md) | Notable changes |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development workflow and engineering rules |
| [SECURITY.md](SECURITY.md) | Security boundary and reporting |

## License

Apache License 2.0. See [LICENSE](LICENSE).
