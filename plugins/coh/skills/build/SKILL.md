---
name: build
description: "Build a CoH repository harness from an accepted, current Build Plan. Use only when the user explicitly invokes $coh:build and has authorized that plan. Do not use for read-only assessment, migration, general coding, or checking an existing harness."
---

# CoH Build

Construct only the repository harness described by an accepted CoH Build Plan. Keep every write recoverable and within the authorization granted for this invocation.

## Preconditions

- Require an accepted Build Plan for the same repository and current live state.
- Recheck repository instructions, Git state, candidate targets, and ownership before writing.
- If the plan is absent, stale, ambiguous, or targets a different repository state, stop with `NEEDS_SETUP` and recommend `$coh:set-up`. Do not improvise a build.
- Preserve unrelated user changes and never reset, rebase, overwrite, or clean them.

## Write boundary

The accepted plan may authorize only:

- the canonical `.coh/model.json` and its transaction journal;
- a new, previously unowned CoH Guide or Sensor;
- a clearly machine-owned extension or pointer whose owner and precedence are explicit.

Stop before changing human-authored meaning or precedence, an existing Guide, Fact Map, `AGENTS.md`, test, validation owner, coverage policy, CI, deployment configuration, credential, permission, paid service, or external system unless the user separately and explicitly authorizes that exact change.

Hook execution never inherits `$coh:build` authorization.

## Workflow

1. Re-run the Build Plan's read-only preflight against live state.
2. Resolve every target to an exact path and classify it as absent, machine-owned, human-owned, ambiguous, or conflicting.
3. Stop on any unplanned ownership or authority conflict.
4. Apply the smallest accepted changes. Prefer `../../scripts/bootstrap_transaction.py` for create-only, recoverable publication, and publish the canonical model last.
5. Validate the model with `../../scripts/validate_harness_model.py`.
6. Verify idempotence and run only repository checks confirmed to be side-effect-free and within the accepted plan.
7. Report exactly what changed and which evidence layers were actually established.

Use `../../references/maintenance-contract.yaml` as the shared invariant contract. Consult `../../references/proof-boundaries.md`, `../../references/harness-concepts.md`, and `../../references/source-registry.md` as needed.

## Terminal results

Return a `CoH Build Result` with exactly one terminal state:

- `READY`: a valid, enabled Harness Model exists and all required build checks passed.
- `BLOCKED`: publication was not completed or readiness cannot be established. Include the exact blocker and recoverable next step.
- `NEEDS_SETUP`: no accepted current Build Plan can safely authorize construction.

List changed files, validation commands and results, remaining unverified proof layers, and any separately authorized follow-up. Never describe proposal, syntax success, or a Hook observation as behavioral or production proof.
