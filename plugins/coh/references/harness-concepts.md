# Harness Engineering Concepts

Harness Engineering shapes the environment around a coding agent so correct work is easier to discover, perform, verify, and maintain. It is broader than prompt wording and narrower than rebuilding an entire development platform.

The useful question is not “Which standard files should every repository add?” It is “Which recurring failure mode can the smallest durable control prevent or expose?”

## Guide and sensor

A **guide** helps the agent choose the right path. Examples include a thin routing index, an architecture note, a runbook, or task-specific instructions.

A **sensor** mechanically observes a claim. Examples include a schema check, import-boundary test, migration check, or tracked-file inventory validator.

Guides and sensors complement each other:

- A guide without evidence can become stale narrative.
- A sensor without routing or explanation can be difficult to interpret and maintain.
- A repository may need only one of them for a narrow risk.

## Feedforward and feedback

**Feedforward controls** reduce mistakes before action. They include entrypoint routing, explicit boundaries, narrow permissions, and known-good commands.

**Feedback controls** detect or absorb mistakes after action. They include tests, CI, browser checks, trace review, failure logs, and post-run reconciliation.

A small harness often combines one feedforward control with one feedback control and a named owner.

## Computational and inferential work

**Computational claims** can be checked mechanically with stable inputs and a deterministic oracle. File coverage, schema shape, import edges, and command exit status are common examples.

**Inferential claims** depend on context or judgment. Whether a recommendation is minimal, whether an architecture is understandable, or whether a user journey is acceptable usually requires reviewed evidence.

Do not turn an inferential claim into a hard gate merely because an LLM can grade it.

## Progressive disclosure

Keep entrypoints thin and route to deeper material only when relevant. A root agent guide should help locate authority rather than reproduce every architecture detail, command, and exception.

Progressive disclosure reduces stale duplicated guidance and lowers the chance that an agent anchors on irrelevant context.

## Live evidence first

Repository structure, commands, test results, runtime behavior, provider integrations, and production state can drift. Inspect current evidence before recommending a control. Background references explain patterns; they do not establish facts about the target.

When evidence is incomplete, label the claim `UNKNOWN`. When sources disagree, label it `CONFLICTING`. Do not convert a plausible inference into an observed fact.

## A harness is not an artifact checklist

Possible artifacts include agent routing, a Fact Map, architecture documentation, validation entrypoints, test sensors, ratchets, runbooks, failure logs, debt registers, continuity records, or approval boundaries. None is universally mandatory.

Select an artifact only when:

1. A concrete recurring or high-impact risk is evidenced.
2. Existing controls do not already own the concern.
3. The artifact has a maintainer or a credible maintenance trigger.
4. Its proof boundary can be stated honestly.
5. Its cost is proportionate to the risk.

## Small closed loop

A durable minimal loop usually contains some subset of:

1. Route the task to the narrowest authority.
2. Record only facts supported by current evidence.
3. Check deterministic invariants mechanically.
4. Keep uncertain signals visible without blocking.
5. Assign ownership and a maintenance trigger.
6. Feed repeated failures back into guidance, tests, or a measured ratchet.

Stop when the demonstrated risk is covered. Additional infrastructure without a demonstrated gap is not maturity; it is maintenance debt.
