# Agent Effect Integrity — 2026-11-22 follow-up experiments

## Status and scope

**Reproduced source-level correctness anomaly in the Python reference implementation; no unauthorized execution demonstrated. Do not label as a confirmed security vulnerability. No upstream issue, pull request, or security disclosure has been submitted.**

Source tested: [Microsoft Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit), pinned at commit `f85abe1fffc5aaeed716a94bd6654677329215b9`.

Research run: [GitHub Actions #45043019954](https://github.com/mathesonlj16-eng/approval-autopsy-oidc-lab/actions/runs/45043019954). This run tested the original upstream protocol package in **source-only isolation** because the full consolidated installation requires a dependency not published to PyPI in the attempted install. The upstream `test_approval_protocol.py` test file itself was not modified.

Results: **14/14 research tests passed; 62/62 upstream control tests passed**. A passed characterization test can still document an undesirable observed behavior.

## Experiment A — SQLite effect adapter

Nine new tests used an isolated SQLite database, actual `ApprovalCoordinator` authorizations, and an application-owned idempotent effect adapter.

Observed:
- Effect succeeds after authorization; prior approval cannot be reused.
- A simulated crash after approval consumption and before the effect leaves the approval spent with no effect. A *new* explicit authorization can recover.
- A lost response after SQLite commit leaves one effect. Reauthorization with the same operation ID and exact approved payload is deduplicated by the adapter.
- Twelve separately approved concurrent calls for one operation ID produced exactly one committed effect.
- Reusing an operation ID for a different approved payload was rejected by our adapter.
- Failure before transaction commit rolled back, and a later separately authorized attempt could succeed.
- A restarted adapter detected an already committed effect.
- Changed action parameters could not use the old approval.

**Interpretation:** Our adapter's transactional idempotency provides at-most-once effects for synthetic tickets. This behavior must **not** be attributed to Microsoft's approval protocol, which binds and consumes approvals, rather than guaranteeing exactly-once external side effects. The tests use injected exceptions, not real operating-system process termination.

## Experiment B — concurrent required approval stages

Two *different*, required human stages were tested using a controllable `InMemoryApprovalStore` subclass to synchronize both voters' first `get_entries()` snapshot. No source code was changed in the upstream coordinator.

- Sequential stage-0 (Alice) then stage-1 (Bob) approvals produced ALLOW and successful execution validation.
- In the controlled concurrent interleaving, both legitimate votes were appended with `previous_entry_digest=None` because each had read the empty chain before the other appended.
- The coordinator recorded an `Outcome.ALLOW` resolution after receiving both required votes.
- `validate_for_execution()` subsequently returned `CHAIN_TAMPERED` and denied execution.

**Preliminary root cause:** `submit_entry()` sequences multiple store operations (`get_request`, `get_entries`, `append_entry`, `_maybe_resolve`) without a transaction spanning the whole submission. The in-memory store protects its individual operations with a lock, but these operations are not one atomic append-and-resolve transaction. The test deliberately schedules concurrent input, and it uses the same coordinator and store within one process.

**Observed impact:** A valid multi-stage approval may become unexecutable in this interleaving (availability/correctness), while the guard fails closed. **No permission bypass, data leak, or real production effect was shown.** Whether this violates intended support for concurrent approval submissions in production depends on the documented integration contract and other storage backends; this is not yet independently confirmed by maintainers. Searches of obvious issue titles/keywords did not establish prior reporting status definitively.

## Next validation and review gates

1. Compare the behavior against real `govern()` integration, and verify whether parallel votes are supported by the intended API contract.
2. Test a production-like persistent store with multiple coordinator instances before generalizing beyond the in-memory reference.
3. Design a minimal per-request atomic submission solution, accounting for multi-process workers and immutable audit evidence; test sequential and concurrent behavior.
4. Seek human approval **before contacting maintainers or submitting a report**. The upstream repository requests private reporting for security vulnerabilities.
5. If the finding is a mere documented limitation, record that conclusion instead of labeling it novel.

No cloud GPUs, third-party services, credentials, or user data were used in these experiments.
