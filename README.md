# AI Control Centre

AI Control Centre is a local-first foundation for building a deterministic AI development and control platform.

The project is being developed incrementally from explicit software boundaries rather than starting with autonomous agents or unrestricted tool execution.

## Current Status

**Development stage:** Alpha

**Current focus:** deterministic task lifecycle, validation, readiness, and execution boundaries.

The current implementation provides:

- Project management
- Goal management
- Task management
- Explicit task lifecycle transitions
- Goal lifecycle reconciliation
- Validation
- Task readiness evaluation
- Execution admission
- Execution start boundary
- Execution outcome recording
- Execution target selection
- Execution adapter registration
- Execution coordination
- Deterministic persistence and lifecycle handling

The current execution layer does **not** yet provide:

- Real shell execution
- Browser execution
- Git execution
- GitHub automation
- LLM execution
- Autonomous agent loops
- Unrestricted tool execution

These capabilities are intentionally deferred until the underlying control boundaries are stable and well tested.

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
