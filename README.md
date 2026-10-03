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
- Execution admission, start, and outcome recording (library level)
- Execution target selection and adapter registration (library level)
- Execution coordination (library level)
- Deterministic local JSON persistence with atomic writes

"Library level" means the component exists and is tested, but no CLI command invokes it yet.

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

Goal project names are not validated, state files have no locking or schema version, and a `running` task has no recovery path. These are tracked as G3, G4, and G5 in [docs/STATUS.md](docs/STATUS.md).

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

aic project add <path>                      Register a local project
aic project list                            List registered projects

aic goal create "<description>" --project <name>
aic goal list
aic goal status <goal-id>                   Show a goal (reconciles and saves its status)

aic task create --goal <goal-id> "<title>"
aic task list
aic task status <task-id>
aic task readiness <task-id>                Check whether a task is ready for execution
aic task ready <task-id>                    pending -> ready (parent goal must be open)
aic task start <task-id>                    ready -> running (must pass readiness)
aic task complete <task-id>                 running -> completed
aic task fail <task-id>                     running -> failed
```

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
| `AIC_DATA_DIR` | Directory for `projects.json`, `goals.json`, and `tasks.json` | Windows: `%LOCALAPPDATA%\AI-Control-Centre`; otherwise `~/.local/share/ai-control-centre` |
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
| [ROADMAP.md](ROADMAP.md) | Phased plan |
| [CHANGELOG.md](CHANGELOG.md) | Notable changes |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development workflow and engineering rules |
| [SECURITY.md](SECURITY.md) | Security boundary and reporting |

## License

Apache License 2.0. See [LICENSE](LICENSE).
