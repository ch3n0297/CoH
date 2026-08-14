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
6. Run `../../scripts/build_plan.py context --repository <repo> --json` to bind
   the Plan to the current Codex Task, repository identity, and Git HEAD. If
   that context is unavailable, return `INSUFFICIENT_EVIDENCE` rather than an
   executable Plan.
7. Draft a canonical BuildPlan v1 conforming to
   `../../schemas/build-plan.schema.json`. Include the candidate Model digest,
   exact `adopt|create` operations, every material authority and target
   precondition, and explicit proof boundaries.
8. Present both the canonical single-line JSON bytes and their SHA-256 digest.
   Also present every candidate Model/Guide/Sensor source byte payload and the
   digest referenced by the Plan. The Plan and candidate sources exist only in
   this Task response; do not write them into the repository or treat them as a
   durable authority.

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
- canonical BuildPlan v1 JSON and `plan_sha256` when the decision is
  `NEEDS_HARNESS`;
- candidate source payloads whose exact digests are bound by that Plan;
- the exact follow-up invocation `$coh:build <plan_sha256>`;
- authorization boundaries and blockers;
- the proof layer each proposed check could establish.

The result is a plan only. Never imply that a proposed file, route, Sensor, or
validation result already exists. A Plan is executable only in this same Task,
against the recorded HEAD and material inputs, after the user explicitly
accepts its displayed digest.
