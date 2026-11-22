# Human review guide — approval-submission atomicity candidate

**Prepared:** 2026-11-22. **Status:** internally staged patch; never submitted to Microsoft. This is a correctness/availability finding, not a demonstrated authorization bypass or security vulnerability.

## Exactly what changes

The patch is staged under [upstream-ready](../upstream-ready) using **native Microsoft source paths**. An automated job copies those seven normal Python files into a pristine checkout at commit **f85abe1fffc5aaeed716a94bd6654677329215b9**, runs tests, and exports a portable `git diff` artifact. This branch is **not itself a fork of Microsoft’s repository**, and it contains historical research files; use the generated isolated patch, not the whole branch, for a future upstream contribution.

Three modified files:

1. **`store.py`** introduces an optional `AtomicApprovalStore` protocol with `approval_transaction(request_id)`. The existing in-memory store implements the operation using its shared `RLock`, protecting one Python process.
2. **`coordinator.py`** wraps complete vote submission (read prior entry, append sealed entry, resolve and update request) in the backend transaction where available. It adds `require_atomic_submission=False`; legacy custom stores continue with an explicit warning, or fail closed if strict mode is enabled. A deferred expiry exception ensures a rejected late vote can still commit its `EXPIRED` terminal resolution.
3. **`__init__.py`** exports the optional store capability.

Four new tests cover deterministic parallel-stage races, duplicate IDs, expiry/cancellation/advisory votes, legacy compatibility and strict mode, and the real `govern()` wrapper with synthetic SQLite side effects. A separate research-authored SQLite store verifies atomicity across **separate OS processes**, and worker-kill tests verify rollback.

## Reproduced failure

Unmodified installed Microsoft approval protocol:
- Two valid, required concurrent approvals can each read an empty predecessor list.
- A terminal `ALLOW` resolution can be stored, but both entry hashes point to `None` instead of forming a chain.
- `validate_for_execution` correctly rejects this as `chain_tampered`.

This is a fail-closed **availability/correctness** result. It is not evidence of unauthorized execution. The forced scheduling interleaving proves possibility but does not measure production frequency.

## Human review required before submission

The [Microsoft contributor policy](https://github.com/microsoft/agent-governance-toolkit/blob/main/CONTRIBUTING.md) welcomes AI-assisted development but requires the submitting human to meaningfully review the *specific* changes and be able to explain and defend the design. It explicitly does **not** accept unreviewed autonomous PRs by default, and says maintainers expect to engage with the human author directly rather than an AI responding to review comments.

Before signing off, the human contributor should be able to explain:
- Why individually locked store methods do not make a multi-step submission atomic;
- Why an in-process `RLock` cannot protect separate worker processes;
- Why a database transaction or equivalent CAS is necessary for distributed backends;
- Why the default legacy mode retains the race and why strict mode prevents unsafe submission on unsupported backends;
- Why the `EXPIRED` state must be persisted even when an expired vote raises an exception;
- Why another design, such as an atomic append-and-resolve store method, might be preferable.

## Pending maintainer choices and limitations

- **API compatibility:** new `AtomicApprovalStore` is optional, but legacy stores are **not fixed** until they implement it. The desired default strictness and migration path remain to be agreed.
- **Database locks:** our SQLite fixture uses global `BEGIN IMMEDIATE`, not the per-request locking a scalable persistent backend should use. It is not Microsoft production code.
- **Same-stage conflict behavior:** ADR-0030 expects conflicting votes for the same stage to be rejected and audited; the original coordinator currently admits them while pending and later resolves `DENY`. This is **not** changed in the atomicity patch.
- **Tests:** target branch CI must pass after switching from generated edits to ordinary source files. Broader unrelated monorepo areas have not been exhaustively tested.
- **Licensing / attribution:** keep original Microsoft license headers and credit any third-party architectural prior art if referenced. Do not represent original research as maintainer-confirmed.
- **DCO / CLA:** the eventual commit needs a genuine `Signed-off-by` trailer from the human contributor, plus the Microsoft CLA workflow. No sign-off or acceptance has been fabricated here.
- **Security reporting:** if future research shows a policy bypass, follow upstream private vulnerability reporting, not public bug reporting.

## Contribution checklist

- [x] Deterministically reproduce baseline defect.
- [x] Validate prototype and regression suite against an installed pinned package (earlier research run).
- [x] Stage direct source-file changes and native tests in an isolated preparation branch.
- [ ] Confirm dedicated clean-patch workflow and portable `git diff` artifact.
- [ ] Human reviews and understands the exact source changes.
- [ ] Apply patch to a real fork, sign the upstream commit using the human's genuine identity.
- [ ] Confirm maintained upstream base and negotiate optional/strict migration semantics.
- [ ] Only after approval, submit and engage personally with maintainers.

**No fork, issue, pull request, signed contribution, or upstream maintainer contact has been performed by this research.**
