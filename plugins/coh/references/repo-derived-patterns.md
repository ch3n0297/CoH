# Repository-Derived Harness Patterns

These patterns are privately derived and generalized. They contain no facts about the repository currently under analysis. Use a pattern only after live evidence shows the matching risk.

## Small closed-loop spine

**Use when:** Repeated agent work loses orientation, skips validation, or leaves no maintained feedback path.

**Do not use when:** A direct task and existing tests already provide sufficient orientation and feedback.

**Required live evidence:** Repeated failure examples, current entrypoints, existing tests and checks, and a credible maintainer.

**Suggested control level:** Guidance for routing; hard gates only for deterministic checks; report-only for uncertain maintenance signals.

**What it proves:** A selected concern has routing, evidence, verification, ownership, and a maintenance trigger.

**What it does not prove:** That every repository risk is covered or that runtime and production behavior are healthy.

## Thin entrypoint routing

**Use when:** Contributors or agents repeatedly choose the wrong documentation, module, or command because the repository has several authorities.

**Do not use when:** The repository is small and one current README already routes work accurately.

**Required live evidence:** Root instructions, documentation structure, task categories, and examples of misrouting or duplicated guidance.

**Suggested control level:** Guidance, backed by a static link or path-closure check only when path existence is a stable invariant.

**What it proves:** The entrypoint routes named task classes to current authority.

**What it does not prove:** The linked content is semantically correct or the implementation works.

## Evidence-backed Fact Map

**Use when:** A large or fast-changing repository repeatedly suffers orientation drift and facts can be anchored to stable evidence.

**Do not use when:** The repository is small, a current architecture source already owns the facts, or there is no maintainer for freshness.

**Required live evidence:** Tracked-file inventory, current modules and entrypoints, recurring fact questions, stable evidence paths, and existing map ownership.

**Suggested control level:** Guidance for semantic facts; static hard gate for deterministic inventory and anchor closure; report-only for suspected semantic drift.

**What it proves:** Named files or anchors remain present and the declared inventory matches the checked revision.

**What it does not prove:** Runtime behavior, architectural intent, browser journeys, provider integrations, or production health.

## Validation ownership map

**Use when:** Checks exist but agents cannot tell which command owns a claim, which environment is required, or how missing dependencies should be reported.

**Do not use when:** One documented command already provides accurate ownership and failure semantics.

**Required live evidence:** Manifests, scripts, CI definitions, environment requirements, test suites, and actual command outcomes.

**Suggested control level:** Guidance for routing; deterministic entrypoint checks may be hard gates.

**What it proves:** Each named validation claim has an owner, execution boundary, and expected evidence artifact.

**What it does not prove:** A suite passed unless the exact suite ran successfully in its required environment.

## Legacy-growth ratchet

**Use when:** Existing violations are measurable and cannot be safely removed in one change, but new growth can be prevented.

**Do not use when:** The baseline is unstable, the count is not meaningful, or fixing the invariant immediately is safer and cheap.

**Required live evidence:** Reproducible baseline, stable counting rule, examples of valid and invalid cases, and an owner.

**Suggested control level:** Ratchet.

**What it proves:** The measured violation count did not exceed the recorded baseline, or moved in the required direction.

**What it does not prove:** Existing violations are harmless or the subsystem is correct.

## Report-only heuristic

**Use when:** A signal can help reviewers find candidates but lacks a stable semantic oracle.

**Do not use when:** The result would automatically block, delete, rewrite, or authorize broad cleanup.

**Required live evidence:** Representative true and false positives, a review rubric, owner, and storage for adjudication results.

**Suggested control level:** Report-only until a narrower claim is calibrated.

**What it proves:** Only that the detector selected candidates under its current rule.

**What it does not prove:** The candidates are defects, dead code, duplicate authority, or safe to remove.

## Harness maintenance loop

**Use when:** Facts, checks, or instructions are maintained project state and drift has caused repeated failures.

**Do not use when:** The artifact is temporary, disposable, or has no credible owner.

**Required live evidence:** Drift examples, change triggers, current ownership, existing release or review workflow, and the cost of stale state.

**Suggested control level:** Guidance plus deterministic freshness checks where possible; uncertain drift signals remain report-only.

**What it proves:** Named maintenance events have owners and defined checks.

**What it does not prove:** External state remained unchanged between observations.

## Thin lifecycle adapter

**Use when:** A real lifecycle event can route or enforce one high-confidence local boundary without collecting sensitive content.

**Do not use when:** The host lacks the required event, contributors need incompatible local configuration, or the automation would pretend a nearby event is equivalent.

**Required live evidence:** Supported lifecycle events, activation scope, failure behavior, privacy boundary, and uninstall path.

**Suggested control level:** Guidance or a narrow hard gate for deterministic local invariants.

**What it proves:** The adapter ran for the supported event and applied its declared local rule.

**What it does not prove:** Every agent surface or unsupported event received equivalent protection.
