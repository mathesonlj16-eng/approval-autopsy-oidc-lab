# Draft upstream contribution — atomic approval submissions

**Internal preparation only. Candidate verified against the installed package; not submitted or shared with Microsoft.**  
**Prepared:** 2026-11-22 | **Target:** Microsoft Agent Governance Toolkit, Python `agentmesh` approval protocol at `f85abe1fffc5aaeed716a94bd6654677329215b9`.

## Proposed PR title

fix(agentmesh): serialize approval entry submission across the store transaction

## Problem

`ApprovalCoordinator.submit_entry()` fetches the preceding hash-chain entry, appends a new entry, and writes an approval resolution using independent `ApprovalStore` calls. Individual operations on `InMemoryApprovalStore` use a lock, but the combined submission is not atomic.

When two legitimate required-stage votes arrive at the same time, both can see the same previous entry. A terminal `ALLOW` resolution may then contain two entries that reference the same predecessor, leading `validate_for_execution()` to return `chain_tampered`. This **fails closed** (denies legitimate execution); no unauthorized execution or disclosure has been observed.

## Minimal reproduction

In a synthetic two-stage chain, open one approval request and submit the stage-0 and stage-1 `ALLOW` decisions from separate workers. Force both original workers to read the same empty predecessor list before either appends. Both votes are accepted, the resulting resolution can be `ALLOW`, but the chain is invalid and execution validation denies. Sequential submission passes.

The failure reproduced both with two threads sharing the original in-memory store and with two separate worker processes using a research-authored SQLite implementation of the upstream `ApprovalStore` interface. The concurrency barrier guarantees the interleaving; it **does not estimate actual workload frequency**.

## Candidate change

- Keep the original `ApprovalStore` structural protocol and all its existing methods.
- Introduce an **optional** `AtomicApprovalStore` protocol exposing `approval_transaction(request_id)` and perform the full `submit_entry` inside this transaction where supported.
- Implement the capability for the built-in `InMemoryApprovalStore` using its existing reentrant lock.
- Provide a new opt-in `require_atomic_submission=True` coordinator setting that refuses nontransactional third-party stores before a vote can be appended.
- For legacy custom stores with the default setting, preserve existing behavior but emit a runtime warning explaining that they still lack the concurrent-submission guarantee.
- Preserve an expired request's durable terminal `EXPIRED` resolution when a late vote causes a protocol error. This required deferring the public exception until after a successful transaction commit.

A research-only SQLite adapter uses `BEGIN IMMEDIATE` as an example of a cross-process implementation; it is **not** part of the suggested upstream patch, and per-request transactional locking is preferable for a production database.

## Evidence at preparation time

- [Passing pinned-source test run — 21 focused research tests and 62 original Microsoft protocol tests](https://github.com/mathesonlj16-eng/approval-autopsy-oidc-lab/actions/runs/45046899316). The run includes controlled original-failure reproduction, cross-process SQLite comparison, abrupt-worker-termination recovery, durable expiry checks, and Ruff/format validation of the changed source files.
- [Previously passing installed-package run — 14 native tests, 76 upstream approval/govern/bridge tests](https://github.com/mathesonlj16-eng/approval-autopsy-oidc-lab/actions/runs/45045546646). This predates the latest expiry refinement.
- [Latest passing full installed-package acceptance — 21 native research tests, 76 unchanged Microsoft tests, cross-process and expiry checks](https://github.com/mathesonlj16-eng/approval-autopsy-oidc-lab/actions/runs/45046989480). This run used the locally built ACS SDK and reinstalled the candidate patched core from source. All checks passed, including Ruff lint (excluding baseline UP035/UP045) and source formatting.
- The workflow outputs the actual source `git diff` as an artifact. All modifications in GitHub remain on the user's separate research branch.

## Additional semantics discovered during review

ADR-0030 says conflicting submissions for a single stage are rejected and audited. The current coordinator instead accepts two distinct entries for one pending stage with opposite decisions, then resolves `DENY`. The **deny is safe**, but the admission behavior may diverge from the written design. The research includes a separate characterization test for this. **Do not silently expand the atomicity fix to change stage-conflict semantics** without maintainer agreement.

Duplicate submissions carrying the same `chain_entry_id` remain idempotent, including under concurrent calls. New votes after terminal resolution are rejected; expired and cancelled requests reject votes. Advisory decisions cannot satisfy human approval stages.

## Contribution requirements confirmed from the upstream repository

- Read the nearest `agent-governance-python/agent-mesh/AGENTS.md` and preserve trust and audit guarantees.
- Follow `CONTRIBUTING.md`, including Microsoft's contributor license agreement (CLA) and a developer certificate of origin **Signed-off-by** trailer on each eventual PR commit. The original author's actual authorized identity must be used; **no identity or signature has been invented here**.
- Avoid unrelated source modernization and maintain reproducible, minimal diffs. Upstream source has pre-existing `UP035` / `UP045` typing deprecations; the research lint gate excludes these while checking other lint rules and formatting.
- Respect `SECURITY.md`: if a later version of the finding demonstrates a security vulnerability, report it privately. This research has so far shown a fail-closed correctness/availability defect, not a policy bypass.
- Obtain explicit owner approval **before opening a public issue, submitting a pull request, contacting maintainers or publishing a security advisory**.

## Open maintainer decisions / non-goals

1. Does the published approval-store contract require atomic concurrent submissions, and should strict atomicity be the default in a future major version?
2. How should old third-party backends migrate without an unsafe silent fallback?
3. Should the accepted design expose an explicit atomic append-and-resolve method instead of a store-level transaction context manager?
4. How should the transaction be scoped on durable distributed stores, given that a local Python lock does not protect multiple processes?
5. Should the same-stage conflict behavior be corrected separately?
6. Review broader native package suite and any unexpected regressions. Do not claim full monorepo certification or a tested production persistent backend.

**No external PR or issue exists as a result of this document.**
