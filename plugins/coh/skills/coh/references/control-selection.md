# Control Selection

Choose control strength from the nature of the claim, not from how important the topic sounds.

## Decision dimensions

Evaluate four dimensions:

1. **Determinism**: Can the same inputs produce an unambiguous result?
2. **Evidence quality**: Is the oracle direct, current, and reproducible?
3. **Actionability**: Can a failure point to a bounded corrective action?
4. **False-positive cost**: What valid work would be blocked by an incorrect signal?

High importance alone does not justify a hard gate. A high-impact but ambiguous signal may need human review rather than automatic blocking.

## Guidance

Use guidance when judgment depends on task context or when several valid solutions exist.

Examples:

- Choosing which architecture reference applies.
- Deciding whether a small task needs a Fact Map.
- Explaining how to inspect a provider integration safely.

Guidance should route to evidence and name exceptions. Avoid universal prose that cannot stay synchronized with the codebase.

## Hard gate

Use a hard gate only when the invariant is deterministic, high-confidence, actionable, and cheap enough to run at the appropriate boundary.

Examples:

- A required manifest has valid schema.
- A forbidden dependency edge exists.
- A generated inventory no longer matches tracked files.
- A release archive contains a credential-shaped value.

A hard gate must state what it proves and what it does not prove. Schema validity does not prove runtime correctness; a passing static boundary does not prove production health.

## Ratchet

Use a ratchet when legacy violations are measurable but cannot be removed safely in one change. Freeze or reduce a known baseline instead of demanding immediate perfection.

A credible ratchet needs:

- A reproducible baseline.
- A stable counting rule.
- A rule that prevents new growth or requires monotonic improvement.
- An owner and an exit condition.

Do not use a ratchet when the baseline itself is noisy or easily gamed.

## Report-only

Use report-only for heuristic signals, early detectors, prioritization aids, or candidate cleanup lists.

Examples:

- Possible duplicate documentation.
- Complexity or entropy candidates.
- LLM-graded recommendation quality.
- Suspected stale facts without a deterministic freshness oracle.

Report-only findings must not silently block work, delete code, or authorize refactors. Review repeated results before promotion.

## Promotion boundary

Promote a signal only when the claim becomes narrower and the evidence improves.

For report-only to ratchet:

- Freeze the behavior family, fixtures, and rubric.
- Repeat observations across multiple builds or revisions.
- Review outputs and measure reviewer agreement.
- Resolve high-severity disagreements.
- Record an explicit promotion decision and owner.

For ratchet to hard gate:

- Reduce the claim to a binary machine-observable invariant.
- Demonstrate low false-positive behavior.
- Define failure remediation.
- Reassess after material changes to the host, model, prompt, fixture, or oracle.

Broad semantic judgments such as “this repository needs a harness” or “this design is minimal” should remain reviewed decisions.

## Selection record

For every recommended control, record:

- Evidence and failure mode.
- Owner.
- Selected level.
- Why a stronger level is not justified.
- What the control proves.
- What it does not prove.
- Maintenance or promotion trigger.
