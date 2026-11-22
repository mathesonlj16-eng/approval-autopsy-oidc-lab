# Agent Effect Integrity — first external test result

**Date:** 2026-11-22
**Status:** source-level conformance run succeeded; **no new vulnerability demonstrated**

## Reproducible source and evidence

- Research branch: `research/agent-effect-integrity-2026-11-22`
- Research commit: `d3618dfc40d0b3fb4af256f8f64b3e98f0461a3c`
- Target: Microsoft Agent Governance Toolkit, Python `agentmesh` approval protocol
- Target commit: `f85abe1fffc5aaeed716a94bd6654677329215b9`
- [GitHub Actions run #45000789132](https://github.com/mathesonlj16-eng/approval-autopsy-oidc-lab/actions/runs/45000789132)
- Evidence artifact: `agent-effect-integrity-conformance` (stored on the run, 14-day retention)

## Result

- **3 / 3** synthetic external protocol probes passed:
  1. Changed action parameters denied.
  2. Concurrent consumption allows at most one.
  3. Consumption followed by a synthetic crash before external effect leaves no effect; retry denied.
- **62 / 62** upstream protocol tests passed unchanged (run in temporary isolation to avoid unrelated package fixtures).
- Source checked out at the precise target SHA. No production actions or credentials used.

## Important installation limitation

The initial full-package installation failed because the core package requested `agent-control-specification>=0.4.0b0,<0.5`, which PyPI did not provide in that run. This is **not a security vulnerability**.

The successful run imported the original approval-protocol source via a test-only bootstrap that bypasses the broad parent package initializers. Therefore these results apply **to the isolated pinned protocol**, not the fully installed multi-component framework.

## Research assessment

The one-time approval consumption and binding controls behave as documented in this test. The simulated crash shows that one-time authorization does not guarantee successful or exactly-once external execution. This is an expected distributed-systems boundary and is not evidence of a bug.

**Next experiment:** use a realistic, disposable effect-adapter integration and investigate how it records, reconciles, and recovers ambiguous outcomes. Compare any observation to documented guarantees and existing tests before disclosing or filing an issue. Never represent these baseline results as an undiscovered defect.
