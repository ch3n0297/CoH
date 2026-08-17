<h1 align="center">CoH</h1>

<p align="center">
  <a href="https://github.com/ch3n0297/CoH/actions/workflows/validate.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/ch3n0297/CoH/validate.yml?branch=main&amp;style=flat-square&amp;label=CI" alt="CI status">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/github/license/ch3n0297/CoH?style=flat-square" alt="MIT License">
  </a>
  <a href="plugins/coh/README.md">
    <img src="https://img.shields.io/badge/Codex-Plugin-000000?style=flat-square" alt="Codex Plugin">
  </a>
  <a href="plugins/coh/README.md">
    <img src="https://img.shields.io/badge/Python-3%20stdlib%20only-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3 standard library only">
  </a>
</p>

**Repository-specific guidance and validation routing for Codex.**

CoH — short for Code of Harness — is an opt-in Codex plugin that routes repository
tasks through repository-owned guidance and declared validation evidence, without
creating a second source of truth. It targets repositories that already have
`AGENTS.md`, architecture guides, runbooks, tests, or named validation owners, where
Codex still has to re-derive which of those apply on every task.

Public alpha (`0.3.0-alpha.3`), Codex-only, POSIX macOS/Linux.

## Is this for your repository?

CoH helps when there is existing authority to route to — `AGENTS.md`, architecture
guides, runbooks, tests, or a named validation owner — but nothing yet tells Codex
which of those apply to a given task, so it re-derives that on every run.

It is less likely to help a small, single-path repository without meaningful
guidance or validation ownership: there is nothing for CoH to route to.

## Quick start

```bash
codex plugin marketplace add ch3n0297/coh --json
codex plugin add coh@coh --json
```

Start a new Codex Task, then:

1. Run `$coh:set-up` — a read-only inspection that produces a canonical BuildPlan v1
   and its `plan_sha256`.
2. Review the BuildPlan. In the **same Task**, run `$coh:build <plan_sha256>` to
   accept and construct exactly that plan.
3. Optionally run `$coh:check` at any time — an independent, read-only diagnosis of
   the existing Harness Model. It is not a required third setup step.

## Before CoH / After opting in

**Before:** a repository has `AGENTS.md`, an architecture guide, a runbook for one
module, and a Sensor script that checks for contract drift — but nothing connects
them. Each Codex task re-reads the tree and guesses which apply.

**After opting in:** `$coh:build` records references and relationships between these
existing files in `.coh/model.json` — it does not copy or duplicate their prose. A
later task tagged `[route:<id>]`, or matching a declared path prefix, routes to the
existing Guide and Fact references and to the existing Sensor, using their current
content as authority. If the referenced evidence is missing or stale, CoH leaves it
untrusted rather than treating it as a pass. This does not, by itself, claim to
improve task correctness — it routes to what the repository already owns and
reports whether the declared evidence is current.

## How it works

1. **Inspect** — `$coh:set-up` performs a read-only Need Gate over the live
   repository and produces canonical, task-bound BuildPlan v1 bytes plus
   `plan_sha256`.
2. **Accept and build** — `$coh:build <plan_sha256>`, in the same Task, rechecks
   HEAD and every material input, then constructs only the accepted plan.
3. **Route and verify** — a `READY` Harness Model routes exact `[route:<id>]` tags
   or declared path prefixes to existing Guide/Fact references and Sensors;
   `$coh:check` can re-diagnose it independently at any time.

## Trust and evidence

Verified deterministically on this exact checkout:

- Public CI ([`.github/workflows/validate.yml`](.github/workflows/validate.yml))
  and `scripts/validate_package.py` validate deterministic package/runtime
  contracts only — package closure, Python stdlib imports, public fixtures, Hook
  regressions, receipt adversarial cases, and recoverable Bootstrap transactions.
- BuildPlan freshness and repository preconditions fail closed: a stale HEAD or a
  changed material input blocks Build rather than proceeding on stale data.
- Hooks never write repository files; they cannot edit Guide files, Fact Maps,
  `AGENTS.md`, tests, validation logic, CI, or deployment configuration.
- Repository-owned files remain the authority; CoH stores references and
  relationships, not copies of their prose.
- `READY` means Harness construction closure only — the declared Model, routes,
  authorities, Sensors, and maintenance references are structurally valid. It does
  not mean repository tests passed.
- A validation receipt proves only its declared evidence layer.

None of the above constitutes a behavioral-improvement claim, a security
attestation, or browser, live-provider, production, or human-review evidence.

## Limitations

- Public alpha: `0.3.0-alpha.3`.
- Codex-only; no other agent host is supported.
- Hook command contract targets POSIX macOS/Linux and is tested in Linux CI only.
  Native Windows is not supported.
- Runtime dependency is the Python 3 standard library only.
- No universal validation runner — validation evidence is whatever the repository
  declares, checked structurally.

## Validate this exact checkout

```bash
python3 scripts/validate_package.py
```

This evidence applies only to the exact checked-out source. It does not prove that
CoH improves coding-task behavior or establish browser, live-provider, production,
security, or human-review evidence.

## Package

- Marketplace: [`.agents/plugins/marketplace.json`](.agents/plugins/marketplace.json)
- Plugin: [`plugins/coh/`](plugins/coh/)
- Version: `0.3.0-alpha.3`

See the [plugin README](plugins/coh/README.md) for package contents, Model/receipt
schemas, the full host support matrix, legacy configuration handling, and upgrade
guidance.

## License

MIT. See [LICENSE](LICENSE).

---

If CoH addresses a recurring routing or validation problem in your Codex workflow,
try it on one repository. Star the project to follow the public alpha.
