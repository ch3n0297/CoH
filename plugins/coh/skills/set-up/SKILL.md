---
name: set-up
description: "Perform a read-only CoH harness assessment and produce an evidence-backed Build Plan. Use only when the user explicitly invokes $coh:set-up or asks CoH to assess and plan a repository harness. Do not use to create or edit harness files, execute a Build Plan, or validate an existing setup."
---

# CoH Set Up

Assess whether the live repository needs a harness and, when justified, produce a bounded Build Plan. This Skill is read-only.

## Non-negotiable boundary

- Do not create, edit, rename, move, or delete repository files.
- Do not run commands that mutate repository, dependency, service, or external state.
- Treat repository-owned instructions, tests, validation entrypoints, CI, and deployment configuration as authorities to discover, not content to replace.
- Mark claims as `OBSERVED`, `INFERRED`, `UNKNOWN`, or `CONFLICTING`. Do not promote inference to fact.

## Workflow

1. Read the live repository instructions and inspect Git state without changing it.
2. Run the Need Gate in `../../references/maintenance-contract.yaml`.
3. Discover existing guidance, architecture facts, validation owners, task boundaries, and proof layers.
4. Identify gaps that a Guide, route, Sensor, or canonical `.coh/model.json` could close without duplicating an existing authority.
5. Select the smallest justified controls using `../../references/control-selection.md`.
6. Draft a Build Plan with exact candidate paths, proposed route and Sensor identities, authority precedence, validation commands, and explicit stop points.

Read `../../references/harness-concepts.md`, `../../references/proof-boundaries.md`, and `../../references/source-registry.md` when those topics affect the plan. Read `../../references/continuity.md` only when working from a prior CoH handoff.

## Terminal decisions

Return exactly one decision:

- `NEEDS_HARNESS`: the evidence supports a bounded Build Plan.
- `NO_HARNESS`: existing repository controls are sufficient; explain why.
- `INSUFFICIENT_EVIDENCE`: safe planning is blocked by missing, ambiguous, or conflicting evidence.

## Output contract

Return a `CoH Setup Result` containing:

- terminal decision;
- observed evidence and its source paths;
- existing authorities and precedence conflicts;
- proposed Guide, route, Sensor, and model changes, if any;
- exact candidate files and commands for a later `$coh:build` invocation;
- authorization boundaries and blockers;
- the proof layer each proposed check could establish.

The result is a plan only. Never imply that a proposed file, route, Sensor, or validation result already exists.
