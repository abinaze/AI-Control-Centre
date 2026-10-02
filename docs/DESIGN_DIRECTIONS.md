# Design Directions

**Status: Research.** Nothing in this document is implemented, and nothing here is a commitment. It records ideas that came out of design exploration so they are not lost and so they do not cause the project to be redesigned every time a new idea appears.

For what actually exists, read [STATUS.md](STATUS.md) and [ARCHITECTURE.md](ARCHITECTURE.md). A capability moves out of this document only when it is added to [ROADMAP.md](../ROADMAP.md) and then implemented with tests.

The exploration notes also pointed to external material: Model Context Protocol proposals and its skills extension, agent-memory security guidance, and agent frameworks such as LangGraph and AutoGen. Those references were **not independently re-verified** when this document was written. Treat them as pointers to investigate, not as citations.

## Governing rules

These rules are already consistent with the code and are the constraints any future layer must respect.

```text
AI should reason.
AIC should control.
Tools should execute.
Validation should verify.
Humans should remain in control.
```

1. **Control state is authoritative.** Task status, goal status, and execution outcomes live in the control layer. No other layer may change them silently.
2. **Proposals are not actions.** A planner, agent, or model may propose. Admission and policy decide what is permitted to happen.
3. **Execution success is not correctness.** An agent saying "done" is a claim. It needs evidence and validation before it is accepted.
4. **Deterministic first, AI later.** Build the deterministic foundation, then let AI populate and use it.
5. **External content is data, not authority.** Anything read from files, websites, repositories, or other servers is untrusted input and must never be treated as policy or as a requirement.

## Two planes

```text
                AI CONTROL CENTRE
                       |
         +-------------+-------------+
         |                           |
   CONTROL PLANE               COGNITIVE PLANE
   (authoritative)             (contextual)
         |                           |
  Project -> Goal -> Task     Knowledge graph, memory,
  Validation, Readiness       context, relationships
  Admission, Execution
```

The control plane answers: what should happen, and is it allowed to happen? It exists today.

The cognitive plane would answer: what do we know, how is it connected, and what should be considered? It does not exist.

The cognitive plane may relate a task to a concept. It must not change the task's status.

## NeuroIntelligence (cognitive graph)

A proposed cognitive layer: a typed graph connecting knowledge, goals, tasks, evidence, and experience.

**Nodes** would carry an identity, a type, a description, a status, a source, supporting evidence, and timestamps.

**Node status** would be explicit rather than a numeric confidence score:

```text
UNKNOWN, PROPOSED, SUPPORTED, VERIFIED, CONTRADICTED, REJECTED
```

**Source categories** keep the system from treating its own guesses as facts:

```text
HUMAN-PROVIDED, AI-INFERRED, OBSERVED, VERIFIED, UNVERIFIED
```

**Relationship types** would include `depends_on`, `requires`, `implements`, `tests`, `supports`, `contradicts`, `derived_from`, `related_to`, `blocks`, and `causes`.

**Linking to the control plane** is where the value would come from. For example, a requirement node `requires` an authentication node, which is `implemented_by` a task, which `produces` evidence that `validates` the requirement. Neither a mind map nor a task list can answer "which test proves this requirement" alone.

**Contradiction detection** is a candidate first capability. If a verified requirement says "local-only" and a proposal introduces an external cloud API, the proposal is flagged and held for a human decision instead of silently becoming reality.

**First version should be deterministic and human-populated.** Nodes and relationships are added by hand through commands before any model is allowed to populate the graph.

## Memory (Research)

Memory should be several layers rather than one store:

- Working: what the system is doing now
- Episodic: what happened in earlier executions
- Semantic: general concepts
- Project: facts about one project
- Procedural: how things are usually done
- Evidence: where a fact came from

Properties worth designing in from the start: provenance on every item, versioning instead of overwriting (a fact has `valid_from` and `valid_until`), expiry, user-visible list, inspect, export, and forget controls, and strict project boundaries so one project's private knowledge cannot leak into another.

A poisoning defense follows from the contradiction idea: a new memory that conflicts with an older rule is flagged, not silently substituted.

## Planning, workflow, and events (Research)

- **Planner proposes, never executes.** Flow: goal, then proposed plan, then validation, then human or policy approval, then an accepted task graph.
- **Task graph.** Tasks would move from a flat list per goal to a dependency graph, which enables blocked-task detection, parallelizable work, critical path, and impact analysis.
- **Workflow abstraction.** A deterministic workflow core, written in this project, before any external framework.
- **Event boundary.** Meaningful operations emit events (for example `TASK_READY`, `EXECUTION_STARTED`) that other components subscribe to, instead of calling each other directly.
- **Durable execution.** Checkpoints so that a crash mid-run can be recovered deterministically.

## Governance (Research)

- Policy engine evaluating every action: allowed, denied, or approval required.
- Approval requests with scope and risk.
- Tool side-effect classification: pure, read-only, reversible, irreversible, external side effect.
- Short-lived, narrowly scoped capability grants instead of broad standing access. An agent role is not a permission.
- Budgets and quotas: tool calls, file writes, retries, runtime.
- Operating modes (safe, development, controlled autonomous), a global emergency stop, and per-agent and per-tool kill switches.
- Data classification that decides what may be sent to a remote model.

## Observability and explainability (Research)

- Correlation identifiers carried from goal through task, execution, attempt, and event.
- Causality on events, so the system can answer "why did this happen".
- State transition history recording who, when, and why.
- A "why?" view for any task: why it exists, why it was ready, why it was executed, why it completed.
- Replay and time-travel inspection, which require event history.

## Quality practices (Research)

- Write invariants down and test them as properties, not only as examples. A first set is already tracked in [STATUS.md](STATUS.md#invariants).
- Contract tests at each boundary.
- Dry-run and simulate modes that show what would happen without doing it.
- Fault injection and chaos-style tests for recovery paths.
- Evaluation and regression suites once models are involved.

## Small infrastructure features (Research)

Individually minor, collectively what makes a control platform dependable:

```text
cancellation, timeouts, retry policy, idempotency keys, optimistic concurrency,
leases, heartbeats, resource locks, checkpoints, rollback, schema migration,
feature flags, secret handling, export and import of project state
```

A general principle worth adopting early: every persisted object has an identity, a version, a status, created and updated timestamps, and provenance.

## How the research maps to verified gaps

The most practical use of these ideas right now is to address gaps already found in the code. See [STATUS.md](STATUS.md#known-gaps).

| Gap | Research idea that applies |
| --- | --- |
| G1: CLI bypasses readiness | Centralized transition guards; invariant INV-4 |
| G4: non-atomic persistence | Schema migration, optimistic concurrency, atomic writes |
| G5: `running` tasks never recover | Timeouts, heartbeats, leases, checkpoints |
| No execution history | State transition history, execution records, correlation identifiers |
| G3: free-text project names | "Everything has identity": a goal should reference a project by identity |
| G10: duplicated constant | Schema-first architecture: one definition per concept |

## Provisional ordering

The exploration suggested this order. Only the first two steps are done. The hardening work in [ROADMAP.md](../ROADMAP.md) (Phase 2.5) was inserted after the code was verified and sits before everything else.

```text
Execution outcome                     done
Execution coordinator                 done (library level)
Hardening (Phase 2.5)                 proposed
Execution state and history
Task dependencies
Workflow and event boundary
Evidence
Cognitive foundation                  nodes, relationships, context, provenance
Memory
Policy and approval
Tool registry
Agent registry
Local model interface
Planner
Real controlled execution
```

## Not now

Do not add any of the following until the boundaries beneath them bind every execution path:

- LLM integration
- Autonomous agents and agent loops
- Automated coding
- Shell or subprocess execution
- Browser automation
- Git and GitHub automation
- Model routing
- Cloud APIs

The point of keeping this inventory is to have a place to put new ideas without acting on all of them. Most of these ideas should stay here.
