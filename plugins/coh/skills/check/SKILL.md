---
name: check
description: "Check an existing CoH Harness Model, routes, Sensors, Hook eligibility, and receipt evidence without modifying the repository. Use only when the user explicitly invokes $coh:check or asks CoH to diagnose an installed harness. Do not use to plan or build a harness."
---

# CoH Check

Inspect an existing CoH harness and explain whether it is structurally valid and runtime-eligible. This Skill is read-only.

## Non-negotiable boundary

- Do not create, edit, repair, migrate, rename, move, or delete files.
- Do not run a repository command until its side effects are understood and confirmed acceptable for a read-only check.
- Do not treat a missing or rejected receipt as a build failure; construction state and validation evidence are separate findings.
- Do not let Hooks, receipts, or generated projections override repository-owned authorities.

## Workflow

1. Inspect repository instructions, Git state, and `.coh/model.json` from live files.
2. Run `../../scripts/validate_harness_model.py` against the repository.
3. Check declared authorities, route containment and overlap, Sensor ownership, maintenance metadata, and Hook runtime eligibility against `../../references/maintenance-contract.yaml`.
4. Classify each validation result by the proof layers in `../../references/proof-boundaries.md`.
5. Review nonce-bound receipts only as bounded evidence for their declared layer. Missing, stale, ambiguous, or invalid evidence is never a pass.
6. Recommend `$coh:set-up` for a missing or conceptually outdated harness, or `$coh:build` only when a current accepted Build Plan authorizes the needed repair.

Use `../../references/harness-concepts.md`, `../../references/source-registry.md`, and `../../references/continuity.md` when those details affect the diagnosis.

## Output contract

Return a `CoH Check Result` containing:

- structural status: `VALID`, `INVALID`, or `MISSING`;
- runtime eligibility: `READY`, `BLOCKED`, or `NOT_APPLICABLE`;
- route, Guide, Sensor, maintenance, and Hook findings;
- receipt evidence status, kept separate from construction status;
- commands actually run and their exit status;
- proof layers established and layers still unverified;
- the recommended next Skill, if any.

Never report a fix as completed, because this Skill performs no writes.
