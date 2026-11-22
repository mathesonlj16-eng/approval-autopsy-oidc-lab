# Cross-process approval atomicity: SQLite reproduction and transaction design

**Date:** 2026-11-22  
**Research status:** reproducible **source-level** availability/correctness defect with a working transaction prototype; **not a verified security vulnerability or a production-ready upstream fix**.

## Evidence and exact source

- Microsoft Agent Governance Toolkit, Python `agentmesh` approval protocol pinned to `f85abe1fffc5aaeed716a94bd6654677329215b9`.
- [Successful GitHub Actions run #45044381478](https://github.com/mathesonlj16-eng/approval-autopsy-oidc-lab/actions/runs/45044381478), research workflow at commit `4b55fca5f5533408bf96940feb9ede6e69a662e9`.
- The run's artifact `agent-effect-integrity-conformance` includes exact upstream SHA, original and patched logs, a code diff, Python environment, and crash-recovery logs (artifact retained 14 days).
- Our disposable SQLite implementation: [`sqlite_approval_store.py`](../research-patches/sqlite-multiprocess/sqlite_approval_store.py).
- Two independent spawned worker processes: [`run_cross_process.py`](../research-patches/sqlite-multiprocess/run_cross_process.py).
- Abrupt process termination: [`run_crash_recovery.py`](../research-patches/sqlite-multiprocess/run_crash_recovery.py).
- Candidate patch generator: [`apply_patch.py`](../research-patches/approval-atomicity/apply_patch.py).

## Observations

| Experiment | Original pinned coordinator | Transaction-patched coordinator |
| --- | --- | --- |
| Two separate processes, two required approvals, same SQLite DB | **3/3 trials:** resolution ALLOW, validation `chain_tampered`, execution denied | **3/3 trials:** resolution ALLOW, validation `ok`, valid hash chain |
| Worker abruptly exits after writing one vote, before completing submission | One incomplete approval entry persisted; no resolution; later retry can complete with two records | Transaction rolls back; zero incomplete entries; later retry completes with one record |
| Sequential/two-thread control from earlier run | Sequential passes; two-thread forced race fails | Both pass |
| Existing research and effect-adapter tests | 14 source-level research characterization cases passed before patch | 12 protocol/effect-adapter cases passed after patch |
| Unmodified upstream `test_approval_protocol.py` | **62 passed** | **62 passed** |

All data are synthetic. The two processes were spawned independently; each constructed its own coordinator and SQLite connection. The concurrent experiment uses a two-party barrier **inside the disposable SQLite adapter** to force both unpatched workers to observe the same empty entry snapshot, rather than relying on timing luck. In the patched case the first transaction blocks the second writer at `BEGIN IMMEDIATE`, preventing both from observing a stale snapshot simultaneously.

The crash experiment uses actual `os._exit(87)` in a disposable child process, after the entry is appended. The original store's individual write commits survive termination; the patched transaction's uncommitted entry is rolled back by SQLite when the connection is forcibly closed by process exit.

## Root cause and why the patch works

Original `ApprovalCoordinator.submit_entry` performs several individual store operations: it reads entries, computes the hash of the previous entry, appends the new entry, and then resolves the chain. The published `ApprovalStore` interface exposes each operation, but **does not require one atomic submission transaction**.

With concurrent workers, independent calls can be individually thread-safe yet jointly inconsistent. An `ALLOW` approval resolution may therefore coexist with an unverifiable approval chain; execution validation correctly fails closed with `chain_tampered`.

The candidate patch introduces a store-level `approval_transaction(approval_request_id)` context covering the full `submit_entry` flow. It uses the built-in `InMemoryApprovalStore` reentrant lock in process, and this independent SQLite prototype supplies an explicit `BEGIN IMMEDIATE` transaction across processes.

**No policy bypass has been shown.** The observed consequence is rejected authorized work and inconsistent audit evidence, not unauthorized side effects.

## Contract-safe upstream design considerations

**The current prototype is not a drop-in patch.** It adds a required `approval_transaction` method to `ApprovalStore`, and fails closed if a custom store lacks it. This is potentially a breaking change for third-party implementations.

A maintainer-ready design would require a deliberate contract/migration choice:

1. Define an explicit `AtomicApprovalStore` contract (or versioned protocol capability), with `approval_transaction(request_id)` and a documented invariant: all entry reads, appends, resolution writes, and status changes for one request occur in the same serialized transaction.
2. In distributed/persistent configurations, **never silently fall back to an in-process lock**. Use a store-provided transactional capability or fail closed with a specific configuration error. Decide the legacy-store migration policy with maintainers.
3. For SQLite, `BEGIN IMMEDIATE` is sufficient for our synthetic fixture but serializes database writers globally. A production PostgreSQL or equivalent adapter should use a per-request row lock or correctly scoped advisory lock within a database transaction.
4. Handle crash and rollback, idempotent retry by `chain_entry_id`, a store-independent correctness oracle, and the interaction with one-time approval consumption.
5. Test with two independently initialized instances and multiple worker processes, plus a full `govern()` or transport integration. Do not mistake the isolated source tests for a deployed system.
6. Confirm support guarantees in ADR-0030, user-visible failure semantics, and maintainer acceptance of any required store interface change before proposing upstream code.

**Alternative worth evaluating:** a single atomic store method that appends a sealed vote and potentially updates resolution under a request version/CAS precondition. This avoids keeping arbitrary coordinator callbacks inside an open DB transaction but requires more extensive protocol/store redesign.

## Limitations

- The SQLite store is **written by this research**, not a Microsoft-supplied production backend; its JSON serialization and coarse database lock are laboratory code.
- The full consolidated Microsoft package was not installed. Its declared dependency on an unpublished PyPI package blocked an initial installation; the project's contribution guide documents a source-install workaround that has not been tested here. We imported only the original unchanged approval protocol source from the pinned repository.
- Only one particular schedule was forced in the concurrency trials; results **do not estimate real-world failure frequency**.
- The successful prototype does not establish the issue affects every persistent store, language SDK, or actual production environment.
- This may be a known limitation or an uncovered correctness requirement. Maintainers have not independently confirmed its novelty or scope.
- No credentials, real agents, live tools, production data, or cloud GPU resources were involved.

## Next decision

Conduct a compatibility/API design review and a full `govern()` integration check before considering upstream PR preparation. **Do not submit an issue, PR, or security report without the owner's approval.** If later evidence establishes a security-relevant defect, follow the repository's private security reporting policy.
