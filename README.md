# CoH Codex Plugin

This repository distributes the **CoH (Code of Harness)** plugin for Codex.
It intentionally contains only the Codex marketplace metadata and the installable
plugin package.

## Install

```bash
codex plugin marketplace add ch3n0297/coh --json
codex plugin add coh@coh --json
```

Start a new Codex task after installation, then begin with:

```text
$coh:set-up
```

Installing CoH does not opt a repository in automatically. Set Up only inspects
and plans. Invoke `$coh:build` after accepting that plan, then use `$coh:check`
for read-only diagnosis. Routing is enabled only by a valid, enabled, `READY`
Harness Model.

## Package

- Marketplace: [`.agents/plugins/marketplace.json`](.agents/plugins/marketplace.json)
- Plugin: [`plugins/coh/`](plugins/coh/)
- Version: `0.3.0-alpha.3`
- Runtime dependency: Python 3 standard library

See the [plugin README](plugins/coh/README.md) for behavior, safety boundaries,
package contents, and upgrade guidance.

## License

MIT. See [LICENSE](LICENSE).
