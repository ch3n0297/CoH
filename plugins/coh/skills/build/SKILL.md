---
name: build
description: "Build a CoH repository harness from an accepted, current BuildPlan v1 digest. Use only when the user explicitly invokes $coh:build <plan_sha256> in the same Task that produced the Plan. Do not use for read-only assessment, migration, general coding, or checking an existing harness."
---

# CoH Build

Construct only the repository harness described by an accepted CoH Build Plan. Keep every write recoverable and within the authorization granted for this invocation.

## Preconditions

- Require an explicit `$coh:build <plan_sha256>` invocation in the same Codex
  Task that produced the canonical BuildPlan v1 bytes.
- Require the digest to match those exact bytes. The Plan must bind the current
  Task hash, repository identity, Git HEAD, candidate Model, material authority
  digests, and target preconditions.
- Recheck repository instructions, Git state, candidate targets, and ownership before writing.
- If the plan is absent, stale, ambiguous, or targets a different repository state, stop with `NEEDS_SETUP` and recommend `$coh:set-up`. Do not improvise a build.
- Preserve unrelated user changes and never reset, rebase, overwrite, or clean them.

## Write boundary

BuildPlan v1 may authorize only these transaction operations:

- the canonical `.coh/model.json` and its transaction journal;
- `adopt` an unchanged existing authority or Sensor whose digest is recorded;
- `create` a new, previously unowned CoH Guide or Sensor at an `ABSENT` target,
  or accept an already matching idempotent target.

Stop before changing human-authored meaning or precedence, an existing Guide, Fact Map, `AGENTS.md`, test, validation owner, coverage policy, CI, deployment configuration, credential, permission, paid service, or external system unless the user separately and explicitly authorizes that exact change.

Hook execution never inherits `$coh:build` authorization.

## Workflow

1. Materialize the exact canonical Plan bytes only in OS temporary storage;
   never write the Plan into `.coh/` or another repository path.
2. Run `../../scripts/build_plan.py inspect` with the accepted digest, then
   recheck Task, repository, HEAD, every material input, candidate source, and
   target precondition. Any mismatch returns `NEEDS_SETUP`.
3. Resolve every target to an exact path and classify it as absent,
   machine-owned, human-owned, ambiguous, or conflicting.
4. Stop on any unplanned ownership or authority conflict.
5. Apply the smallest accepted changes with
   `../../scripts/bootstrap_transaction.py`, passing the accepted digest to
   `prepare`; publish the canonical model last.
6. Delete the temporary Plan after it is staged or invalidated. The transaction
   journal may retain its digest and recovery preconditions, not a durable copy
   with repository authority.
7. Validate the model with `../../scripts/validate_harness_model.py`.
8. Verify idempotence and run only repository checks confirmed to be
   side-effect-free and within the accepted plan.
9. Report exactly what changed and which evidence layers were established.

Use `../../references/maintenance-contract.yaml` as the shared invariant contract. Consult `../../references/proof-boundaries.md`, `../../references/harness-concepts.md`, and `../../references/source-registry.md` as needed.

## Terminal results

Return a `CoH Build Result` with exactly one terminal state:

- `READY`: a valid, enabled Harness Model exists and all required build checks passed.
- `BLOCKED`: publication was not completed or readiness cannot be established. Include the exact blocker and recoverable next step.
- `NEEDS_SETUP`: no accepted current Build Plan can safely authorize construction.

List changed files, validation commands and results, remaining unverified proof
layers, and any separately authorized follow-up. Without a host-signed approval
event, state only that executed bytes matched the digest displayed to the user;
do not claim cryptographic proof of human identity, comprehension, or intent.
Never describe proposal, syntax success, or a Hook observation as behavioral or
production proof.
