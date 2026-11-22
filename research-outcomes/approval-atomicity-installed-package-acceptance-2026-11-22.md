# Approval atomicity — installed package acceptance (2026-11-22)

**Status:** A source-built, fully installed Microsoft Agent Governance Toolkit package passed candidate-patch acceptance. **No upstream submission, maintainer confirmation, confirmed vulnerability, or production deployment tested.**

## Reproducibility

- Upstream pinned at commit **f85abe1fffc5aaeed716a94bd6654677329215b9**.
- Successful [GitHub Actions installed-package run #45045546646](https://github.com/mathesonlj16-eng/approval-autopsy-oidc-lab/actions/runs/45045546646) at research commit **75159be257092481797e94d2397b7cdb784ff809**.
- The run's artifact **agent-effect-integrity-installed-package**, ID **14763362970**, contains installed version evidence, before/after regression logs, diff, dependency checks, native test results, and SQLite process tests (14-day retention).
- Workflow: [full-install workflow](../.github/workflows/agent-effect-integrity-full-install.yml).
- Candidate code: [compatibility patch generator](../research-patches/approval-atomicity/apply_compatible_patch.py).

## Verified package installation

The runner followed the upstream CONTRIBUTING.md source install, including building the locally versioned Rust-backed ACS SDK, which is not available in the required version on PyPI. Installation checks succeeded.

- **agent-governance-toolkit-core 5.0.0**
- **agent-control-specification 0.4.0b0**, built locally from pinned source
- Python 3.12
- The coordinator and **govern()** module were loaded from actual **site-packages** paths, not the research source-import bootstrap.
- The package was then reinstalled after patching the original protocol source, and the newly exported **AtomicApprovalStore** capability was verified.

This is a source-built installed package with installed dependencies. It is **not** a production, hosted, or published-distribution acceptance test.

## Before/after results

| Scenario | Evidence |
| --- | --- |
| Unpatched installed package, sequential two-stage approval | Passed |
| Unpatched installed package, forced parallel valid votes with one coordinator | Expected failure: **chain_tampered** |
| Unpatched installed package, forced parallel valid votes with two coordinators | Expected failure: **chain_tampered** |
| Candidate patched installed package, research tests in upstream native pytest directory | **14 / 14 passed** |
| Candidate patched installed package, unchanged Microsoft approval / govern / bridge suites | **76 / 76 passed** |
| Candidate patched installed package, two separate worker processes sharing research SQLite database | **3 / 3 trials passed** |
| Candidate patched installed package, abrupt worker termination and recovery | Passed: no partial entry survived; later valid retry succeeded |

The expected two prepatch failures are intentional proof of reproduction; they were not counted as remediated test passes. The process race uses a controlled barrier to show a possible interleaving, not to estimate real-world failure rates.

## Fix design and limitations

The optional **AtomicApprovalStore** contract introduces a transaction around the whole approval submission, rather than only locking individual store methods. The built-in in-memory reference store supplies an in-process reentrant lock; our independent SQLite fixture uses a database transaction with **BEGIN IMMEDIATE** across worker processes.

For compatibility, the original eight-method **ApprovalStore** interface remains usable. A legacy backend lacking atomic transactions still runs by default **with a runtime warning**, and therefore **still has the original concurrency risk**. Opt-in **require_atomic_submission=True** rejects nontransactional stores before appending votes. These defaults are a proposed migration strategy, not a maintainer-approved API decision.

The original defect is **fail-closed**: a chain can reach an **ALLOW** resolution but remain unverifiable, so subsequent execution denies with **chain_tampered**. **No unauthorized execution, data leak, or policy bypass was shown.**

The SQLite backend is research-authored, not a Microsoft production adapter. Its coarse database-wide writer lock is a fixture technique rather than the final performance design. The full higher-level **govern()** integration was tested, including synthetic database writes, approval denials, and audit receipts, but no live third-party service or actual multi-stage asynchronous approval transport was exercised.

## Upstream contribution readiness

**Reviewer-facing draft (not sent):** "Python approval coordinator can resolve concurrent valid stages with an invalid hash chain." Under the documented store interface, two independent valid votes may read the same preceding-entry digest and both append entries with stale predecessor links. A transaction spanning the complete submission fixes the reproducible in-memory and research SQLite scenarios.

Remaining gates:
1. Agree on default behavior and migration policy with maintainers; avoid silently promising atomicity to legacy stores.
2. Review same-stage conflicting votes, retry/idempotency, expiry and cancellation, and transaction granularity on durable backends.
3. Polish native regression placement and source lint; run a broader package suite as appropriate.
4. Follow the project's DCO and Microsoft CLA requirements for any eventual contribution.
5. **Obtain the user's explicit approval before contacting maintainers, opening an upstream issue/PR, or filing a security report.** Potential vulnerabilities must use the upstream private security route.

All changes remain on the research branch. The user's main branch and Microsoft's repository are unchanged. No GPUs or paid cloud infrastructure were used.
