# CoH Source Registry

This registry describes the bundled reference set and its authority limits. References support reasoning; they do not override live evidence from a target repository or system.

| ID | Reference or source | Role | Product mapping | Evaluation mapping | Last reviewed | Authority limit |
| --- | --- | --- | --- | --- | --- | --- |
| HE-001 | `harness-concepts.md`; [OpenAI: Harness engineering](https://openai.com/index/harness-engineering/) | Introductory concepts and vocabulary | Small closed loop, progressive disclosure, guides and sensors | Need Gate, duplicate-authority, and proof-boundary cases | 2026-08-04 | Background only; not a repository prescription |
| HE-002 | `control-selection.md`; bundled synthesis | Control-strength decision support | Guidance, hard gate, ratchet, and report-only selection | Control-selection cases and promotion review | 2026-07-31 | General decision model; requires live calibration |
| HE-003 | `proof-boundaries.md`; bundled synthesis | Evidence-layer claim limits | Static, runtime, browser, live-provider, production, and human-review labels | Proof-boundary and receipt cases | 2026-07-31 | Taxonomy only; a named check proves only its actual scope |
| HE-004 | `repo-derived-patterns.md`; privately derived and generalized | Conditional field patterns | Routing, Fact Map, validation ownership, ratchets, and lifecycle adapters | Existing-harness and evidence-precedence cases | 2026-07-31 | Pattern provenance only; contains no target-repository facts |
| HE-005 | `continuity.md`; bundled synthesis | Long-task and handoff guidance | Conditional continuity artifacts | Future long-task and handoff fixtures | 2026-07-31 | Use only when task duration or handoff risk warrants it |
| HE-006 | [Lin et al.: Agentic Harness Engineering](https://arxiv.org/abs/2604.25850) | Deeper evaluation background | Observability fields, paired host run design, and reviewed semantic baselines | `benchmarks/paired-run.schema.json` and report-only eval policy | 2026-08-04 | Research background; its autonomous evolution result does not authorize automatic Guide updates in this project |
| HE-007 | `learning-loop.md`; alpha benchmark findings and bundled synthesis | Real-world learning and interaction review | Semantic receipt observations, protected authority, episode dimensions, and Guide candidate promotion | `../../../schemas/episode-review.schema.json`, runtime receipt tests, and episode-review summarizer tests | 2026-08-09 | Review protocol only; outcomes are descriptive and never authorize automatic Guide updates |
| HOST-001 | [Claude Code plugins reference](https://code.claude.com/docs/en/plugins-reference) | Host packaging contract | `.claude-plugin`, component paths, explicit invocation overlay | Generated-package drift check and future `claude plugin validate` run | 2026-08-04 | Establishes Claude Code packaging only, not plugin behavior |
| HOST-002 | [Claude Code hooks reference](https://code.claude.com/docs/en/hooks) | Host hook contract | `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PLUGIN_DATA}` adapter | Shared runtime environment test and future live hook forward-test | 2026-08-04 | Establishes documented hook fields only, not real-session success |

## Status vocabulary

- **Background**: optional explanatory material.
- **Conditional**: load only when the present task matches the stated risk.
- **Generalized**: distilled from field experience with private details removed.
- **Authority**: current target-repository files, commands, runtime results, or other directly verified evidence.

## Use rule

Start with live repository evidence. Use a bundled reference to clarify a concept or select a control only after confirming that the target shows the corresponding risk. If live evidence conflicts with a reference, preserve the conflict and follow the live evidence for repository-specific claims.

New papers and host sources must also follow `docs/RESEARCH.md` in the source repository: map the source to a product decision, name an evaluation that could falsify the mapping, and record limitations. Do not ship an undifferentiated bibliography inside the Skill.

## Plugin Bootstrap and runtime contracts

The explicit Skill Bootstrap and lifecycle runtime have structural inputs outside this Skill directory:

- `../../../schemas/harness-model.schema.json` describes the one canonical repository Harness Model.
- `../../../schemas/route-registry.schema.json` describes deprecated one-way migration input only.
- `../../../schemas/validation-receipt.schema.json` describes repository-owned validation receipts.
- `../../../schemas/episode-review.schema.json` describes privacy-bounded, human-reviewed real-world episodes.

These Schemas are structural contracts, not repository facts. Bootstrap integrates current live authorities and publishes `READY` only after their references and maintenance declarations validate; otherwise it records `BLOCKED` without inventing confidence. Runtime derives a versioned route projection in memory from `model.json` and additionally verifies containment, anchor presence, route ambiguity, current eligibility, checkout identity, bounded worktree state, selected-route coverage of changed/untracked paths, per-turn nonce, protected validation authority, and evidence hashes. The routing projection is never persisted as a second authority. A local candidate produced by the Stop hook is report-only; it becomes a Guide recommendation only after explicit review against current repository evidence.

`../../../scripts/bootstrap_transaction.py` is a mechanics-only coordinator for adopted and create-only files. It does not select repository semantics, merge human prose, apply a Guide template, or run validation commands. Its journal and staging directory are temporary recovery material, never repository authority.

`../../../scripts/migrate_to_coh.py` is the only repository namespace migrator. It is dry-run by default, journals before the same-parent rename, rewrites only schema-known repository-path fields, and never runs from a lifecycle hook. `../../../scripts/migrate_routes_to_model.py` separately converts `.coh/routes.json` into a `BLOCKED` Model without inventing maintenance ownership.
