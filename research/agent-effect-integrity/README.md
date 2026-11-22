# Agent Effect Integrity — source-level research pilot

**Status:** reproducible synthetic research. **No unauthorized execution or confirmed security vulnerability demonstrated.**

Target: Microsoft's [Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit), Python `agentmesh` action-bound approval protocol, pinned at `f85abe1fffc5aaeed716a94bd6654677329215b9`.

## Verified results

- [GitHub Actions conformance run, November 22, 2026](https://github.com/mathesonlj16-eng/approval-autopsy-oidc-lab/actions/runs/45043019954): **14/14 research cases and 62/62 unchanged upstream protocol tests passed**.
- [Detailed research findings and limitations](../../research-outcomes/agent-effect-integrity-integration-2026-11-22.md).
- Tests run against Microsoft's *unchanged* source code using a test-only importer; no production system was tested.

The 14 research cases consist of 3 protocol baselines, 9 disposable SQLite effect-adapter cases, and 2 controlled parallel approval cases.

The application-owned SQLite adapter enforced idempotency across new approvals after retries, lost responses, and concurrency. **That effect guarantee belongs to our adapter, not to the Microsoft protocol.**

The parallel-approval experiment identified an **availability/correctness candidate** in the reference in-memory store: under a controlled two-stage interleaving, valid votes produced a terminal ALLOW resolution but execution validation returned `chain_tampered` because two entries were linked to the same predecessor snapshot. Sequential approvals validated correctly. The guard failed closed. This result has not been verified on a production storage backend or classified by upstream maintainers.

## Reproduction scope

The original attempt to install the complete consolidated core was blocked by an unpublished declared PyPI dependency. The subsequent workflow imports the exact pinned protocol source directly without modifying it, bypassing the broader package initializer. Therefore these are **source-level protocol and synthetic integration tests**, not a full installed-framework acceptance test. The upstream contribution guide documents an alternate build-from-source installation path that has not yet been exercised here.

All tests use dummy identities, fake ticket operations, and disposable SQLite files. GitHub Actions is configured for read-only repository permissions, a bounded job runtime, and no secrets or live service connections. A simulated crash uses a deliberately injected exception, not an operating-system process kill.

## Research workflow

Before making any external finding claim, verify documented contracts and other backends; develop a minimal solution for concurrent approval-submission atomicity; seek independent reproduction; and obtain user approval before any contact with maintainers. For potential security vulnerabilities, follow Microsoft's private security reporting instructions rather than opening a public issue.

No cloud GPU resources or prepaid credits are involved.
