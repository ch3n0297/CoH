# CoH Codex Plugin

This repository distributes the **CoH (Code of Harness)** plugin for Codex.
It intentionally contains only the Codex marketplace metadata and the installable
plugin package.

## Install

```bash
codex plugin marketplace add ch3n0297/coh --json
codex plugin add coh@coh --json
```

Start a new Codex task after installation, then invoke:

```text
$coh:coh
```

Installing CoH does not opt a repository in automatically. The explicit Skill
inspects the live repository and attempts a bounded Bootstrap before routing is
enabled.

## Package

- Marketplace: [`.agents/plugins/marketplace.json`](.agents/plugins/marketplace.json)
- Plugin: [`plugins/coh/`](plugins/coh/)
- Version: `0.3.0-alpha.2`
- Runtime dependency: Python 3 standard library

See the [plugin README](plugins/coh/README.md) for behavior, safety boundaries,
package contents, and upgrade guidance.

## License

MIT. See [LICENSE](LICENSE).
