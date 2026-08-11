# Proof Boundaries

Verification evidence is layered. A passing result supports only the claim exercised by that result in the named environment and time window.

| Layer | Can support | Cannot establish by itself |
| --- | --- | --- |
| `static` | Structure, tracked inventory, schema, references, dependency edges, source-level invariants | Runtime execution, browser journeys, provider behavior, production health |
| `runtime` | Execution in the specified process, dependencies, data, and environment | Browser UX, real provider behavior when mocked, production behavior |
| `browser` | A specified UI journey in the tested build, role, browser, and backend | Untested roles and routes, real provider behavior when stubbed, broad production health |
| `live-provider` | A specified integration with a real external provider under recorded conditions | Full production deployment health, every account or provider mode, long-term reliability |
| `production` | A specified canary or journey in the live deployment at the observed time | Long-term stability, all regions, all roles, all traffic, untested paths |
| `human-review` | Semantic, product, usability, or risk judgment by identified reviewers | Deterministic regression prevention or exhaustive correctness |

## Static

Static checks are valuable because they are fast and reproducible. Use them for claims that exist in files or graphs: manifests, inventories, imports, route declarations, required documentation fields, or release contents.

Name the exact checkout and checker when freshness matters. Do not say “the integration works” because its configuration file parses.

## Runtime

Runtime evidence must identify the environment, command, dependencies, fixtures, and whether external services were real, mocked, or absent.

A local process passing against fixtures proves that path in that environment. It does not automatically cover UI composition, identity-provider redirects, network policy, or production configuration.

## Browser

Browser evidence should record route, role, build, backend, browser, and relevant network conditions. A rendered page is weaker evidence than a completed user journey with observable outcomes.

Browser tests using mocked providers remain browser evidence, not live-provider evidence.

## Live provider

Live-provider checks use the real external service and should record provider identity, account or tenant scope, time, credential boundary, and tested operation. Avoid exposing credentials in evidence artifacts.

A direct provider API success may bypass the product browser journey. Keep the two claims separate.

## Production

Production evidence identifies the deployed version, environment, role, route or operation, time window, and observed result. A canary is narrow evidence, not a guarantee of global or future health.

Do not use “live system” as an ambiguous substitute for both provider and production.

## Human review

Human review is appropriate for semantics, product quality, architectural judgment, and the calibration of heuristic signals. Record the rubric, reviewer scope, disagreements, and adjudication when the result affects release status.

Human approval does not replace deterministic tests for stable machine-observable invariants.

## Reporting template

For a verification claim, state:

- Layer.
- Target and environment.
- Exact evidence.
- Observation time or revision.
- What passed or failed.
- What the result proves.
- What remains unproved or unknown.
