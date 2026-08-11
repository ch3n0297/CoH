---
name: coh
description: "Use only when the user explicitly asks for CoH (Code of Harness), Harness Engineering, harness bootstrap, harness design, $coh, a Fact Map, or coding-agent harness analysis for a complex codebase or product effort. Do not use for simple edits, routine documentation cleanup, direct repo Q&A, one-off scripts, or straightforward bug fixes."
---

# CoH

Use this Skill to bootstrap or maintain a small, repository-specific control loop for coding agents. On the first explicit invocation, inspect live evidence and attempt the complete flow in the same task: integrate existing authorities, construct the Harness Model, fill only demonstrated Guide or Sensor gaps, validate the result, and publish either `READY` or evidence-backed `BLOCKED`.

Standardize the logical process, not the repository's physical documentation layout. Do not impose a shared artifact template, overwrite human-owned authority, create a second validation owner, or treat model metadata as proof that the code works.

## Activation Boundary

Run this workflow only when the user explicitly requests CoH, Harness Engineering, harness bootstrap/design, a Fact Map, or equivalent work.

- Codex standalone Skill syntax: `$coh`. When installed from the marketplace Plugin, use `$coh:coh`; Claude Code uses `/coh:coh`.
- These namespaced forms are package contracts. Release-level live-host support remains pending until the exact clean CoH candidate forward-test is recorded.
- Plain-language intent may be explicit, but automatic activation semantics remain host-dependent.
- Do not claim slash-command or host support without forward-test evidence.
- If this Skill is loaded without matching intent, handle the task directly.

## First-Call Bootstrap Boundary

An explicit invocation authorizes the smallest repository-local Bootstrap operations needed to construct the requested Harness without another ceremonial confirmation. It does not authorize unrelated product changes or external side effects.

Within that envelope, the Skill may:

- inspect live repository evidence;
- create the canonical `.coh/model.json` and a recoverable Bootstrap journal;
- create a new Guide or Sensor only where no repository-owned artifact already fills the role;
- update a clearly machine-owned extension block or add a removable pointer block without rewriting surrounding human content;
- run an already confirmed, repository-local, side-effect-free validation command;
- finish as `READY`, or preserve the exact blocker and finish as `BLOCKED`.

Stop and request direction before changing human-owned precedence or meaning, protected tests or expected behavior, coverage or required-check policy, CI/deploy semantics, an existing validation entrypoint, external systems or data, paid resources, credentials, or permissions. Do not add a generic wrapper when a repository-owned validation entrypoint already exists.

## Lifecycle Hook Boundary

Lifecycle hooks are runtime adapters, not extra Skills, and never inherit the explicit Bootstrap mutation envelope.

- A repository opts in through one canonical `.coh/model.json`; `.coh/routes.json` is migration input only and is never a second live authority.
- Lifecycle hooks never move the predecessor repository namespace. Predecessor-only repositories degrade with `LEGACY_NAMESPACE_REQUIRES_MIGRATION`; predecessor and `.coh` together degrade with `COH_NAMESPACE_CONFLICT`.
- Routing is active only when `enabled` is true and `construction.status` is `READY`.
- The router selects exact `[route:<id>]` tags or declared repository-relative path prefixes. It does not guess by semantic keyword or scan the whole repository first.
- `BLOCKED`, ambiguous, malformed, legacy-only, or dual-source states produce bounded degraded guidance; an absent or disabled model is silent.
- The `Stop` hook ignores assistant prose. It accepts validation only through a current, nonce-bound, machine-readable receipt emitted by a repository-owned runner.
- A receipt path is an untracked, non-symlinked, non-hard-linked, per-Sensor artifact under `.coh/receipts/`; it may never overlap an authority or protected path. The router records this precondition before issuing a nonce, and Stop rechecks it before excluding that one path from worktree scope.
- A receipt is trusted only when the checkout remains at the prompt-time commit and the selected route covers the entire receipt-bound changed/untracked worktree; neither a later commit nor an explicit route tag authorizes cross-route changes.
- Model construction state (`READY` / `BLOCKED`) and per-run Sensor evidence (`TRUSTED_RECEIPT` / `NO_TRUSTED_RESULT`) are independent.
- Hook output and plugin-local candidates are advisory. They never authorize repository edits.

When maintaining runtime behavior, treat `references/maintenance-contract.yaml` as the shared policy authority and the bundled JSON Schemas as structural contracts.

## When Not To Use

Do not apply this workflow to simple single-file edits, routine documentation cleanup, direct repository questions, one-off scripts, or straightforward bug fixes. If an explicit request reaches a repository where a maintained Harness would add more authority than value, return `NO_HARNESS` with evidence and make no Harness files.

## Maintenance Self-Check

For maintenance, review, packaging, or evaluation work, read `references/maintenance-contract.yaml` first. Check activation, Bootstrap authorization, model/runtime separation, proof layers, packaging, and forbidden regressions against that single contract.

## Bootstrap Workflow

1. **Need Gate** — choose `NEEDS_HARNESS`, `NO_HARNESS`, or `INSUFFICIENT_EVIDENCE`. A first explicit invocation attempts the full Bootstrap when the decision is `NEEDS_HARNESS`.
2. **Live discovery** — inspect `AGENTS.md`, entrypoint docs, manifests, architecture/runbook files, repository structure, existing validation declarations, tests, CI, and environment boundaries. Label material claims `OBSERVED`, `INFERRED`, `UNKNOWN`, or `CONFLICTING`.
3. **Authority integration** — map existing files to logical roles before creating anything. One live file may serve several roles. Preserve human content and choose one authority for each concern.
4. **Route and Sensor design** — define the smallest useful task routes, Guide references, and repository-owned Sensors. If no trustworthy oracle exists, declare `NO_TRUSTED_RESULT`; do not invent a passing Sensor or make that absence look like test proof.
5. **Preflight** — list planned repository writes and commands. Continue only with operations inside the First-Call Bootstrap Boundary. Record other needs as blockers.
6. **Recoverable construction** — use the bundled `../../scripts/bootstrap_transaction.py` (resolved from this `SKILL.md`) for create-only/adopt staging when new repo-specific files are needed. Recover an incomplete prior Bootstrap before starting another, validate references against live files, and publish one canonical model last. Never maintain `model.json` and `routes.json` together. The coordinator does not merge prose or run repository commands; the Agent remains responsible for semantics.
7. **Verification** — run the model validator, idempotence check, and only confirmed side-effect-free repository validation. Keep `static`, `runtime`, `browser`, `live-provider`, `production`, and `human-review` evidence distinct.
8. **Terminal state** — set `READY` only when the model is internally consistent, all declared live authorities resolve, maintenance ownership and triggers are explicit, and no construction blocker remains. Otherwise set `BLOCKED` with fixed codes and evidence references. A missing receipt affects Sensor evidence, not construction state.
9. **Report** — state what was reused, created, changed, not changed, verified, and still blocked. Never describe lower-layer checks as higher-layer proof.

## Need Gate

Choose exactly one:

- `NEEDS_HARNESS`: recurring or high-impact agent risks justify a maintained repository-specific loop.
- `NO_HARNESS`: normal implementation and validation are sufficient.
- `INSUFFICIENT_EVIDENCE`: the decision materially depends on unavailable or conflicting evidence.

Consider repeated failure modes, boundaries, existing controls, validation complexity, evidence freshness, maintenance ownership, and duplicate-authority cost. Repository size alone is not enough.

## Harness Model

`.coh/model.json` is the only mandatory physical artifact for an initialized repository. It records declarations, not generated confidence:

- construction status and evidence-backed blockers;
- live authority references and their logical roles;
- exact routes and their Guide/Fact authority references;
- repository-owned Sensors and proof layers;
- maintenance authority and triggers.

The runtime derives routing projection v2 in memory, including current runtime eligibility. Do not persist or dual-write that projection. Use the bundled `../../scripts/migrate_to_coh.py` (resolved from this `SKILL.md`) for explicit, recoverable predecessor namespace migration; preview it without `--write` first. If the migrated repository contains `.coh/routes.json`, use `../../scripts/migrate_routes_to_model.py` for the separate one-way route conversion. Namespace migration preserves an existing Model's `READY` or `BLOCKED`; route conversion alone must not invent maintenance ownership or claim `READY`. In `BLOCKED`, only authority ids or paths explicitly named by a blocker may be unresolved.

## Output Contracts

For a completed Bootstrap, return a compact `Harness Bootstrap Result` containing:

- Need Gate decision;
- construction state (`READY` or `BLOCKED`) and blockers;
- authorities/routes/Sensors reused or created;
- files changed and preservation boundaries;
- verification commands and proof layers;
- `TRUSTED_RECEIPT` or `NO_TRUSTED_RESULT` only for Sensor evidence actually observed.

For `NO_HARNESS`, provide evidence, why direct handling is sufficient, revisit conditions, and confirm that no Harness files were created.

For `INSUFFICIENT_EVIDENCE`, provide observed facts, missing/conflicting evidence, the smallest next read-only action, and whether user or external input is required. Do not create a speculative model.

## Control Selection and Proof Boundaries

Choose the narrowest justified control:

- **Guidance** for contextual judgment.
- **Hard gate** only for deterministic, high-confidence, actionable invariants.
- **Ratchet** when measurable legacy violations remain but new growth can be prevented.
- **Report-only** for heuristic signals that still need calibration and review.

Keep these proof layers distinct: `static`, `runtime`, `browser`, `live-provider`, `production`, `human-review`. Read `references/control-selection.md` or `references/proof-boundaries.md` when the choice is material.

## Real-World Learning Loop

Keep benchmark correctness and real-world learning separate. Do not calculate a composite Harness score. Preserve `unknown` when a dimension was not observed, and never persist raw prompts, assistant messages, or tool output in review records.

Repeated miss patterns are report-only candidates. Eligibility for human review does not authorize an automatic Guide, test, validation, or CI edit. Read `references/learning-loop.md` before designing semantic observations, protected validation authority, or Guide feedback promotion.

## References

Start with `references/source-registry.md`; load only what the task needs:

- `references/harness-concepts.md`: concepts and vocabulary.
- `references/control-selection.md`: control strength.
- `references/proof-boundaries.md`: evidence-layer limits.
- `references/repo-derived-patterns.md`: conditional repository patterns.
- `references/continuity.md`: long-running work and handoff.
- `references/learning-loop.md`: reviewed episodes and feedback promotion.

Background references are inspiration, never authority for the target repository. Reinspect live files before applying a pattern.

## Recommendation Rules

- Prefer one small closed loop over a checklist of artifacts.
- Route each concern to the narrowest existing authority; integrate before creating.
- Never expose credentials, private provenance, local paths, or session identifiers.
- Missing evidence is not a pass. Fail closed when a real environment cannot be established.
- Do not promote uncalibrated heuristics to blocking controls.
- Do not compress routing, correctness, semantic validation, and interaction quality into one score.
- Do not automatically rewrite repository-owned Guides, Fact Maps, `AGENTS.md`, tests, validation, CI, or deployment policy.
