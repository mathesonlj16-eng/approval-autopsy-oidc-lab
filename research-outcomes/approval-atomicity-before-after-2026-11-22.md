# Approval atomicity: before/after fix experiment

**Date:** 2026-11-22
**Status:** reproducible Python reference-store correctness issue with a successful **prototype-only** fix. No unauthorized actions demonstrated. Not yet a production-wide vulnerability, maintainer-confirmed bug, or upstream contribution.

## Evidence and reproduction

- Target: Microsoft [Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit), Python `agentmesh` approval protocol.
- Pinned upstream source SHA: `f85abe1fffc5aaeed716a94bd6654677329215b9`.
- Research branch: `research/agent-effect-integrity-2026-11-22`.
- [Successful GitHub Actions run #45043743418](https://github.com/mathesonlj16-eng/approval-autopsy-oidc-lab/actions/runs/45043743418).
- CI artifact `agent-effect-integrity-conformance` includes the unpatched and patched regression logs and `approval-atomicity-prototype.diff` (GitHub artifact retention: 14 days).
- The patch generator is [`research-patches/approval-atomicity/apply_patch.py`](../research-patches/approval-atomicity/apply_patch.py).
- The 3-case regression is [`research-patches/approval-atomicity/test_atomicity_regression.py`](../research-patches/approval-atomicity/test_atomicity_regression.py).

## Before/after experiment

Two independent, required approval stages are configured with synthetic identities, using a controlled interleaving on the first prior-entry read.

| Check | Original upstream protocol | With prototype patch |
|---|---|---|
| Sequential valid votes (control) | Pass | Pass |
| Concurrent votes, one coordinator | **Fail**: `chain_tampered` (expected reproduction) | Pass |
| Concurrent votes, two coordinators sharing one store | **Fail**: `chain_tampered` (expected reproduction) | Pass |
| Unchanged upstream protocol tests | 62 passed | 62 passed |
| Pre-existing synthetic protocol and SQLite effect tests | 12 passed (within the 14-case baseline) | 12 passed |

The original-run 14-case suite also passed, including the controlled characterization cases **which assert the existing failure**. Hence those passes do not mean the original implementation was correct.

The expected-failure step is strict: exactly the two parallel regression cases must fail specifically with `chain_tampered`; the sequential control must pass. The workflow then applies the proposed patch only in its ephemeral checkout and requires all three regression cases to pass, alongside 62 unchanged upstream protocol tests and 12 existing synthetic tests.

## Root-cause hypothesis, supported by observed execution

`ApprovalCoordinator.submit_entry()` performs multiple independent store calls, including `get_entries()`, `append_entry()`, and resolution operations. `InMemoryApprovalStore` protects each individual operation with a reentrant lock, but does not hold a lock through an entire submission.

When two valid votes race, each can compute the same empty prior-entry digest. Both may then append hash-linked entries pointing to no predecessor. The coordinator can reach an `Outcome.ALLOW` resolution, but `validate_for_execution()` detects a broken audit chain and **denies** execution.

This is **fail-closed availability/correctness behavior**, not an authorization bypass.

## Candidate patch

The prototype adds a store-scoped `approval_transaction(request_id)` context contract. `submit_entry()` invokes it across the complete vote/resolve operation. `InMemoryApprovalStore` implements the contract with its existing reentrant lock; consequently multiple coordinators sharing that store serialize submissions.

An implementation without the transaction method is rejected explicitly rather than continuing with an unprotected write.

**Important limitations:**

1. The proposed `ApprovalStore` contract addition is a **breaking API change** for third-party stores; no compatibility plan has been approved.
2. A Python `RLock` protects only a shared in-process store; **it does not guarantee cross-process or distributed atomicity**. A durable implementation would need an appropriate database transaction plus row/advisory locking and idempotency handling.
3. The successful tests import Microsoft's unmodified protocol source directly, bypassing its broader package initializer. The full consolidated package installation was previously blocked by an unavailable PyPI dependency (the project's CONTRIBUTING.md documents a source-build alternative). This is **not a complete deployed-framework test**.
4. The harness synchronizes two threads deliberately; it is not a statistical estimate of failure frequency in real workloads. No destructive actions, credentials, real customer data, or hosted agent permissions were used.
5. We have not proven this is novel, exploitable, or present in other language SDKs or storage backends.

## Research next steps (no external submission yet)

1. Evaluate a compatibility-preserving transaction API and whether the documented approval contract promises concurrently safe submissions.
2. Reproduce with a disposable persistent DB and distinct processes/coordinators, not only a shared in-memory reference.
3. Compare with the `govern()` integration and real approval transport, including audit receipts.
4. Present the limited findings to the owner for approval before contacting upstream. Follow Microsoft's private security process if later evidence establishes a security vulnerability; otherwise use standard contributor guidance.
5. If these are known contract limitations, record that conclusion without claiming an original security finding.

**Neither Microsoft's repository nor the user's default branch has been modified.**
