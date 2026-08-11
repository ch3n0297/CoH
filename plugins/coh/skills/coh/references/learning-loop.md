# Reviewed Learning Loop

Use this reference when evaluating whether a Guide, Sensor, or interaction pattern should change after real coding-agent work. Keep correctness evidence and learning evidence separate.

## Evidence tracks

### Correctness track

Use authoritative tests, official evaluators, runtime checks, and repository-owned validation receipts. Record outcome, time, host-local token counters, and tool activity when the host exposes them.

Correctness evidence answers whether the resulting change passed its declared checks. It does not show that the agent read the Guide, chose the right authority, or communicated well.

### Learning track

Review one bounded work episode across these dimensions:

- `route-selection`: the declared route matched the task.
- `guide-use`: evidence shows the agent used the current Guide revision.
- `authority-selection`: the implementation and validation owners were selected correctly.
- `implementation-correctness`: the produced change satisfied the task-level evaluator.
- `semantic-validation`: repository-owned semantic claims were checked, not inferred from test count alone.
- `validation-integrity`: protected tests and validation declarations remained trustworthy.
- `requirement-alignment`: the result matched the user's stated outcome and boundaries.
- `clarification-quality`: material ambiguity was surfaced without unnecessary questioning.
- `evidence-calibration`: claims matched the actual proof layer and remaining uncertainty.
- `followup-actionability`: unresolved work and next evidence were stated concretely.

Record each applicable dimension as `met`, `partial`, `missed`, `unknown`, or `not-applicable`. Do not calculate a composite quality score. A single score hides whether the problem belongs to routing, guidance, implementation, validation, or interaction.

## Semantic Sensor observations

A repository-owned runner may emit receipt observations with `kind: semantic` or `kind: authority`. These observations must include:

- a stable repository-owned `claim_id`;
- `outcome: pass`, `fail`, or `unknown`;
- a bounded evidence file and its SHA-256;
- the receipt's existing nonce, checkout, worktree, and proof-layer bindings.

A semantic observation is not automatically a hard gate. Keep heuristic or model-reviewed claims report-only until the repository has calibrated false positives, assigned an owner, and defined recovery behavior.

## Protected validation authority

A validation declaration may opt in `protected_paths`. The Stop collector compares those path prefixes with `HEAD`. If they changed, a locally passing receipt becomes `NO_TRUSTED_RESULT` with reason `PROTECTED_AUTHORITY_CHANGED`.

This is a trust downgrade, not an accusation and not an automatic revert. Editing a test may be legitimate task work. The candidate records only a change count and hashes of changed repository-relative paths; a human must inspect live evidence before deciding what changed.

## Interaction review privacy

Use the bundled `../../../schemas/episode-review.schema.json` for real-world episode reviews. Bind the review to hashes of the task reference, versioned in-memory routing projection, Guide revision, and supporting evidence. The legacy field name `registry_sha256` denotes that projection digest for receipt-v1 compatibility; it is not the raw `model.json` hash.

Never place raw prompts, assistant messages, tool output, user-identifying prose, credentials, or absolute paths in an episode review. A reviewer may keep private evidence separately and put only its SHA-256 and allowlisted evidence kind in the review record.

Treat SHA-256 as an integrity reference, not anonymization. Do not hash a short dialogue quote directly; hash an access-controlled evidence bundle with a random evidence id, or leave the dimension `unknown` when the retention boundary is not safe.

User feedback becomes a structured outcome such as `requirement-alignment: partial`; it does not become Guide prose automatically. Candidate codes should describe the reusable failure pattern, not quote the conversation.

## Candidate promotion

Run the bundled `../../../scripts/summarize_episode_reviews.py` over reviewed JSONL episodes. A candidate becomes eligible for human review only after it appears in at least three independent episodes spanning at least two task references.

Eligibility does not authorize an update. Before changing a Guide:

1. Reopen the hashed evidence and current repository authorities.
2. Determine whether the recurring cause belongs to the Guide, Harness Model routing declaration, Sensor, host adapter, or task implementation.
3. Propose the smallest change and a falsifiable forward-test.
4. Obtain separate implementation authorization.
5. Record the new Guide revision hash in later episodes; do not rewrite older reviews.

If the evidence is missing, contradictory, or tied to one task only, retain the candidate as report-only.
