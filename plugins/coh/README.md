<div align="center">
  <img src="assets/icon.png" alt="CoH logo" width="112" />
  <h1>CoH</h1>
  <p><strong>Code of Harness for Codex</strong></p>
</div>

CoH is an opt-in codebase harness for coding agents. It helps an agent find
repository-owned guidance, route a task to declared authorities, and distinguish
real validation evidence from unsupported claims.

This is the installable Codex package. It does not include the former project
benchmarks, Claude Code adapter, or development-only build pipeline.

## Install

```bash
codex plugin marketplace add ch3n0297/coh --json
codex plugin add coh@coh --json
```

Start a new Codex task so the new plugin is loaded, then invoke the explicit
Bootstrap Skill from the repository you want to assess:

```text
$coh:coh
```

Installing the plugin alone does not opt a repository in. Routing begins only
when Bootstrap produces a valid, enabled, `READY` `.coh/model.json`.

## What is included

- `.codex-plugin/plugin.json` — plugin identity and Codex interface metadata.
- `skills/coh/` — the explicit Bootstrap workflow and its bounded references.
- `hooks/hooks.json` — opt-in prompt routing and report-only Stop collection.
- `hooks/*.py` — dependency-free Python runtime for model loading, routing,
  containment checks, nonce binding, and receipt review.
- `schemas/` — Harness Model, migration input, validation receipt, and episode
  review schemas.
- `scripts/` — model validation, namespace migration, recoverable Bootstrap
  transactions, and report-only review helpers.

## Core behavior

1. `$coh:coh` performs a Need Gate and read-only repository inspection.
2. If a harness is justified, Bootstrap attempts to construct one canonical
   `.coh/model.json` using live repository authorities.
3. A `READY` model can route exact `[route:<id>]` tags or declared path prefixes.
4. A repository-owned Sensor may produce a current nonce-bound receipt.
5. Stop-time observations remain report-only candidates for human review.

Use the bundled validator against a repository:

```bash
python3 /path/to/installed/coh/scripts/validate_harness_model.py /absolute/path/to/repository
```

## Safety boundaries

- Hooks do not run arbitrary repository commands or block tools.
- Hooks never edit Guide files, Fact Maps, `AGENTS.md`, tests, validation logic,
  CI, or deployment configuration.
- Missing, stale, ambiguous, or invalid evidence never becomes a pass.
- Raw prompts, assistant messages, tool output, credentials, and absolute
  repository paths are not persisted by the lifecycle hooks.
- A validation receipt proves only its declared evidence layer; it is not a
  production, browser, provider, security, or human-review guarantee.
- Report-only candidates never authorize automatic repository changes.

CoH is a workflow and evidence-calibration aid, not a security boundary or
cryptographic attestation system.

## Upgrade from the predecessor plugin

There is no old-ID compatibility shim. Remove the predecessor plugin and
marketplace explicitly, then install CoH:

```bash
codex plugin remove hjc-code-harness@hjc-code-harness --json
codex plugin marketplace remove hjc-code-harness --json
codex plugin marketplace add ch3n0297/coh --json
codex plugin add coh@coh --json
```

Preview repository namespace migration before authorizing any write:

```bash
python3 /path/to/installed/coh/scripts/migrate_to_coh.py /absolute/path/to/repository --json
python3 /path/to/installed/coh/scripts/migrate_to_coh.py /absolute/path/to/repository --write --json
```

## Update

```bash
codex plugin marketplace upgrade coh --json
codex plugin add coh@coh --json
```

Start a new Codex task after an update. Hook-bearing plugins should not be
reinstalled inside the task that is currently using them.

## License

MIT. See [LICENSE](LICENSE).
