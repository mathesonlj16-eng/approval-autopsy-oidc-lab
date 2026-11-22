# Microsoft approval atomicity — upstream-shaped patch staging

This directory contains **normal Python source files**, not a code-generation script. It is a *staged patch*, not a GitHub fork or upstream pull request.

Base: microsoft/agent-governance-toolkit @ `f85abe1fffc5aaeed716a94bd6654677329215b9`. The source files replace the same paths in `agent-governance-python/agent-mesh`. Four test modules are additive under `agent-governance-python/agent-mesh/tests`.

Run the dedicated upstream-patch CI workflow to check source checksums, apply these file replacements to a fresh upstream clone, run Ruff, native pytest, and the cross-process SQLite fixture. The workflow exports a portable `git diff` and an upstream tree copy.

The built-in in-memory store receives a process-local transaction lock. A new optional `AtomicApprovalStore` contract allows stores to provide cross-process atomic submission. Legacy stores remain usable with a warning; strict mode rejects them. This API choice remains subject to maintainer review. Durable EXPIRED transitions are preserved.

**No upstream GitHub issue/PR has been created. No Microsoft source is modified outside the ephemeral CI checkout.** No DCO sign-off or CLA acceptance is asserted.

The additional same-stage conflicting-vote semantics described by ADR-0030 remain a separate potential issue and are not changed here.
