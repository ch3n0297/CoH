# Changelog

## Unreleased

- Release date and verified benchmark aggregates remain pending.

## 0.3.0-alpha.3 - Unreleased

### Added

- Added three explicit Skills: `$coh:set-up`, `$coh:build`, and `$coh:check`.
- Added an evidence-backed Build Plan handoff between read-only assessment and authorized construction.

### Changed

- Split the former single Bootstrap Skill into distinct planning, mutation, and diagnostic responsibilities.
- Moved shared references to the plugin-level `references/` directory so all three Skills use one maintenance contract.
- Updated plugin metadata and onboarding for the three-Skill workflow.

### Safety boundaries

- Set Up and Check are read-only.
- Build requires an accepted current Build Plan and is limited to its explicit repository targets.
- Lifecycle Hooks remain plugin-wide adapters and never inherit Build authorization.

## 0.3.0-alpha.2 - Unreleased

### Changed

- Renamed the author identity to `hjcloog` and the Plugin, Skill, marketplace, and package identity to `coh`, displayed as CoH; Code of Harness is explained in Plugin metadata instead of the title.
- Moved the repository contract to `.coh/`, advanced the in-memory routing projection and worktree digest domains to v2, and intentionally invalidated predecessor receipts.
- Added the explicit, dry-run-by-default `scripts/migrate_to_coh.py` command for recoverable, one-way repository namespace migration.
- Removed implicit compatibility behavior for the predecessor Plugin identity; users must uninstall the old Plugin and marketplace before installing `coh@coh`.

### Evidence boundary

- Existing benchmark observations remain evidence from the predecessor pre-release identity; their raw observations, traces, patches, and evidence hashes are unchanged.
- The predecessor host forward-test record is not CoH release evidence. Release readiness remains blocked until both hosts are rerun from the exact clean `0.3.0-alpha.2` candidate.

## 0.3.0-alpha.1 - Unreleased

### Added

- Repo-local Claude Code and Codex marketplaces with generated, tracked distributable packages.
- English application-grade README and three-layer Host → Repository → Reviewed Loop architecture diagram.
- Fixed 36-run SWE-bench Verified campaign with a post-campaign treatment-integrity amendment: Claude remains condition-comparable, while the Codex enabled/disabled labels are retained as nominal records but excluded from comparative claims.
- Sanitized dual-host forward-test evidence and a reproducible clean install/invoke/uninstall runner.
- Structured weekly adoption snapshots, a generated dashboard, and five bounded community issue drafts.
- Opt-in protected validation-authority checks and evidence-hashed semantic receipt observations.
- Privacy-bounded real-world episode reviews with dimension summaries and report-only promotion thresholds.
- A four-cell self-hosted pilot, hidden evaluator, strict episode-review recorder, and isolated Codex treatment-profile proof for future campaigns.
- Canonical Harness Model v1, dependency-free validator, one-way legacy migration, and recoverable create-only Bootstrap coordination.
- MIT License, Code of Conduct, public contribution guidance, security reporting policy, bibliography, and adoption evidence definitions.

### Changed

- Standardized plugin, marketplace, package, and release metadata on `0.3.0-alpha.1`.
- Kept one callable Skill while replacing the live `routes.json` authority with one canonical `model.json` and an in-memory routing projection; receipt v1 retains its field name but binds that projection digest.
- Bound trusted receipts to current runtime eligibility and whole-worktree route coverage, so an explicit tag cannot validate cross-route changes with a weaker Sensor.
- Restricted the excluded receipt path to a recorded and rechecked untracked, non-symlinked, non-hard-linked, per-Sensor artifact that cannot overlap repository authorities or protected validation paths.
- Changed the explicit Skill from a read-only Brief handoff to a bounded first-call Bootstrap that ends in `READY` or evidence-backed `BLOCKED`; lifecycle hooks remain repository read-only.
- Reframed self-improvement as report-only candidate generation followed by human review and separate authorization.
- Separated benchmark correctness metrics from routing, Sensor, Guide-use, and interaction-quality evidence.
- Made source-checkout validation independent of the checkout directory name while keeping release-package root-name enforcement.

### Evidence boundary

- The 36-run campaign is complete, but only its Claude cells remain eligible for enabled/disabled comparison; the single-task self-hosted pilot is descriptive evidence, not a general efficiency claim.
- The current host forward-test is provisional because it targets an uncommitted source tree; exact release-commit evidence remains pending.
- OpenCode is not a supported host in this alpha.

All notable changes to this package are documented here.

## 0.2.1 - 2026-08-04

### Added

- Original 512 px icon, retained for CoH, with a compact routing-rail, sensor-node, and validation-check motif.
- Plugin `brandColor`, `composerIcon`, and `logo` interface metadata.
- Deterministic release validation for PNG signature, file size, dimensions, and manifest asset paths.

## 0.2.0 - 2026-08-04

### Added

- Opt-in `UserPromptSubmit` task router discovered from `hooks/hooks.json`.
- Opt-in `Stop` collector that writes only sanitized, report-only candidates under `PLUGIN_DATA`.
- Strict predecessor `routes.json` contract with live path, anchor, containment, overlap, and size checks.
- Exact `[route:<id>]` and declared path-prefix routing without semantic keyword matching.
- Nonce-, registry-, commit-, worktree-, result-, time-, and evidence-bound validation receipt contract.
- Dependency-free registry/worktree validator and deterministic hook runtime tests.
- JSON Schemas for repository route registries and validation receipts.

### Changed

- Plugin remains one callable Skill, while Guide routing and Sensor collection are represented as separate lifecycle responsibilities.
- Release packaging now includes hooks, schemas, and the repository registry validator.
- Maintenance policy now defines hook privacy, authority, degradation, and self-improvement boundaries.

### Safety boundaries

- Hooks fail open and do not block tools.
- Missing or invalid receipts become `NO_TRUSTED_RESULT`, never a pass.
- Raw prompts, assistant messages, tool output, credentials, and absolute repository paths are not persisted.
- No automatic Guide, Fact Map, `AGENTS.md`, test, validation, or CI edits are performed.

## 0.1.0 - 2026-07-31

### Added

- Initial skills-only Codex Plugin manifest.
- Initial predecessor pre-release Plugin and bundled Skill identity.
- Explicit-only predecessor Skill with a three-way Need Gate.
- Compact `NO_HARNESS` and `INSUFFICIENT_EVIDENCE` contracts.
- Six-layer proof-boundary taxonomy.
- Public-safe, progressively disclosed reference set.
- Single machine-readable maintenance contract.
- Twelve report-only behavioral cases across three fixture families.
- Deterministic release-content, privacy, closure, and archive checks.

### Deferred at 0.1.0

- Marketplace installation and new-session discovery evidence.
- Repeated model runs and human-adjudicated behavioral baseline.
- Public publisher identity and open-source license.
- MCP servers, Apps, Hooks, telemetry, and automatic repository analyzers.
