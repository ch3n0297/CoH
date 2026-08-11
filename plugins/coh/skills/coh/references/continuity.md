# Continuity Reference

Use this reference only when a Harness Engineering task is long-running enough that context compaction, process restart, agent handoff, or multi-stage implementation could lose essential state.

## Principles

1. Prefer durable, project-scoped state over conversational memory.
2. Keep handoff artifacts small, current, and evidence-linked.
3. Store project-specific continuity in repository-tracked artifacts when the user authorizes that change.
4. Do not change global host configuration without an explicit request.
5. Do not invent a dependency on a host-specific Skill or command that has not been verified on the active surface.

## Minimal handoff content

A useful handoff records:

- Objective and current success criteria.
- Completed work with evidence.
- Current checkout or artifact identity when relevant.
- Unresolved risks and unknowns.
- Exact next safe action.
- Commands already run and their material outcomes.
- Files changed or intentionally untouched.
- Authorization and external-access boundaries.

Avoid copying raw conversation history, secrets, broad terminal logs, or transient speculation.

## When to recommend a continuity artifact

Recommend one only when at least one condition is present:

- Work spans multiple implementation phases or agents.
- Context reset would cause expensive duplicate discovery.
- External systems create state that must be reconciled later.
- Rollback or recovery requires a durable checkpoint.
- The user asks for a handoff, pause, or resumable plan.

For a short task, the compact Harness Bootstrap Result and normal version-control history are usually enough.

## Proof boundary

A handoff artifact proves only what its linked evidence supports at its recorded revision and time. It does not guarantee that code, CI, provider state, or production remained unchanged after the handoff was written.
