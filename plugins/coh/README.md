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

Start a new Codex task so the new plugin is loaded, then invoke the read-only
Set Up Skill from the repository you want to assess:

```text
$coh:set-up
```

Installing the plugin alone does not opt a repository in. Routing begins only
after you accept the Build Plan and `$coh:build` produces a valid, enabled,
`READY` `.coh/model.json`.

## What is included

- `.codex-plugin/plugin.json` — plugin identity and Codex interface metadata.
- `skills/set-up/` — read-only Need Gate, live discovery, and Build Plan.
- `skills/build/` — accepted-plan construction with bounded repository writes.
- `skills/check/` — read-only model, routing, Sensor, Hook, and evidence checks.
- `references/` — shared concepts, proof boundaries, and maintenance contract.
- `hooks/hooks.json` — opt-in prompt routing and report-only Stop collection.
- `hooks/*.py` — dependency-free Python runtime for model loading, routing,
  containment checks, nonce binding, and receipt review.
- `schemas/` — Harness Model, validation receipt, and episode review schemas.
- `scripts/` — model validation, recoverable Build transactions, and report-only
  review helpers.

## Core behavior

1. `$coh:set-up` performs a read-only Need Gate and produces an evidence-backed
   Build Plan.
2. `$coh:build` requires an accepted current plan, then constructs only its
   authorized repository harness changes.
3. `$coh:check` independently diagnoses the existing Harness Model without
   changing it; it is not a mandatory third setup step because Build performs
   its own deterministic post-check.
4. A `READY` model can route exact `[route:<id>]` tags or declared path prefixes.
5. A repository-owned Sensor may produce a current nonce-bound receipt.
6. Stop-time observations remain report-only candidates for human review.

Use the bundled validator against a repository:

```bash
python3 /path/to/installed/coh/scripts/validate_harness_model.py /absolute/path/to/repository
```

## Safety boundaries

- Hooks do not run arbitrary repository commands or block tools.
- Set Up and Check are read-only. Build writes only within an accepted current
  Build Plan.
- Hooks never inherit Build authorization or edit Guide files, Fact Maps,
  `AGENTS.md`, tests, validation logic, CI, or deployment configuration.
- Missing, stale, ambiguous, or invalid evidence never becomes a pass.
- Raw prompts, assistant messages, tool output, credentials, and absolute
  repository paths are not persisted by the lifecycle hooks.
- A validation receipt proves only its declared evidence layer; it is not a
  production, browser, provider, security, or human-review guarantee.
- Report-only candidates never authorize automatic repository changes.

CoH is a workflow and evidence-calibration aid, not a security boundary or
cryptographic attestation system.

`READY only means` that Harness construction closure is satisfied: the declared
Model, routes, authorities, Sensors, and maintenance references are structurally
valid for the live repository. It does not mean repository tests passed or that
repository behavior is trusted.

## Host support

| Environment | Current contract |
| --- | --- |
| POSIX macOS/Linux | Supported target; Hooks invoke `python3`. Linux is covered by public CI and macOS requires the same POSIX command contract. |
| WSL | Uses the Linux contract; it is not separately claimed as compatibility evidence. |
| Native Windows | Not currently supported or claimed. The package does not yet provide a tested `commandWindows` override. |

An installation or manifest check proves only that Codex can discover the
package. It does not prove that a Hook command executed on an untested host.

## Legacy configurations

CoH does not include a migration Skill or user-facing migration command. Legacy
`.hjc-code-harness/` and `.coh/routes.json` configurations are not runtime
authorities, and Hooks fail closed without moving or rewriting them. Use
`$coh:set-up` to plan a fresh Harness Model, then explicitly authorize
`$coh:build` if construction is appropriate.

## Update

```bash
codex plugin marketplace upgrade coh --json
codex plugin add coh@coh --json
```

Start a new Codex task after an update. Hook-bearing plugins should not be
reinstalled inside the task that is currently using them.

## License

MIT. See [LICENSE](LICENSE).
