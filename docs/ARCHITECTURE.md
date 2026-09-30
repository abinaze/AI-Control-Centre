# Architecture

## Overview

AI Control Centre is a local-first control platform built around deterministic state transitions and explicit control boundaries.

The architecture is intentionally incremental. Each major capability is introduced through a defined contract, an implementation boundary, and tests that verify its observable behavior.

The current architecture is centered on the following progression:

```text
Project
  ↓
Goal
  ↓
Task
  ↓
Lifecycle
  ↓
Validation
  ↓
Readiness
  ↓
Execution Admission
  ↓
Execution Start
  ↓
Execution Coordination
  ↓
Execution Adapter
  ↓
Execution Outcome
```

This progression separates state management and control decisions from the eventual execution mechanism.

## Core Lifecycle Model

The core domain is organized around projects, goals, and tasks.

### Project

A project is the top-level persisted unit of work. It provides the context in which goals and tasks are managed.

Project state is stored locally and managed through deterministic commands.

### Goal

A goal represents a desired outcome within a project.

Goals have an explicit lifecycle and can be reconciled from the state of their tasks.

Goal lifecycle reconciliation derives the appropriate goal state from its associated task state while preserving explicit persisted state rather than silently repairing unrelated inconsistencies.

### Task

A task represents an actionable unit of work associated with a goal.

Tasks have an explicit lifecycle that currently includes pending, ready, running, completed, and failed states.

Task lifecycle transitions are handled explicitly rather than being inferred from arbitrary execution behavior.

## Validation Boundary

Validation provides a deterministic boundary for checking persisted project state.

Validation reports state inconsistencies and invalid conditions without silently modifying persisted state.

This separation allows validation to identify problems without turning validation into an implicit repair mechanism.

## Readiness Boundary

Readiness determines whether a task is allowed to cross into execution.

The readiness evaluator produces an explicit result and reason.

Readiness does not itself mutate lifecycle state.

A task must satisfy the readiness contract before execution-specific starting is allowed.

## Execution Architecture

Execution is separated into explicit boundaries so that execution control is not coupled directly to a concrete execution mechanism.

### Execution Request

An execution request identifies the task and the requested execution target.

The request contract validates that both values are non-empty.

### Execution Admission

Execution admission evaluates whether the requested task satisfies the readiness boundary.

Admission produces an explicit accepted or rejected result and does not itself mutate task state.

### Execution Start

The execution start boundary performs admission and, when admission succeeds, transitions the task from ready to running.

Starting execution is therefore distinct from executing the task.

### Execution Target

An execution target identifies which registered execution adapter should handle a request.

The adapter registry provides explicit target registration and resolution.

Unknown targets are rejected before the task is started so that target resolution cannot leave a task in a running state without a valid execution adapter.

### Execution Adapter

An execution adapter receives an execution request and returns an execution outcome.

The current architecture defines this as a protocol boundary rather than providing unrestricted concrete system execution.

Adapter failures are handled by the coordinator and converted into a failed execution outcome.

### Execution Outcome

An execution outcome identifies the task and declares a completed or failed result.

Outcome recording is responsible for persisting the resulting task state and reconciling the associated goal.

The outcome recorder only accepts execution outcomes for tasks that are currently running.

### Execution Coordination

The execution coordinator connects the execution boundaries in a deterministic sequence:

1. Resolve the requested execution target.
2. Admit the task through the readiness boundary.
3. Start the task and transition it to running.
4. Invoke the resolved execution adapter.
5. Validate the adapter result.
6. Record the resulting execution outcome.
7. Return a structured coordination result.

Adapter exceptions, invalid adapter results, and task identity mismatches are converted into controlled failure outcomes rather than being allowed to bypass outcome recording.

## Design Principles

### Explicit Boundaries

Major state transitions and execution decisions are represented by explicit boundaries rather than implicit side effects.

### Deterministic Behavior

The same persisted state and request should produce predictable control decisions.

### Separation of Concerns

Lifecycle management, validation, readiness, execution control, adapter resolution, and outcome recording remain separate responsibilities.

### No Silent Repair

Validation and normal control operations do not silently rewrite persisted state merely because a derived state differs from stored state.

### Controlled Failure

Execution failures are converted into explicit outcomes so that failure handling remains inside the execution boundary.

## Current Limitations

The current architecture does not yet provide unrestricted execution capabilities.

Concrete system-level execution adapters, execution permissions, execution limits, timeouts, post-execution validation, diagnostics, recovery, and stronger isolation remain future work.

The execution adapter interface therefore represents a controlled architectural extension point rather than an unrestricted command or automation interface.

Future execution capabilities must preserve the existing lifecycle, readiness, admission, and outcome boundaries.
