# Upstream patch preparation — verified result

**Date:** 2026-11-22  
**Status:** scoped, directly applicable source patch prepared and tested; **not a fork, not an opened PR, and not accepted upstream**.

## Precise deliverable

- [Staged Python files](../upstream-ready/): three modified Microsoft source modules plus **two native regression modules**.
- [Passing clean-patch GitHub Actions run #45048349718](https://github.com/mathesonlj16-eng/approval-autopsy-oidc-lab/actions/runs/45048349718). Run SHA: `d96fd895a9208bafefd1daac9c525668472d8c7a`.
- Run artifact: `approval-atomicity-upstream-candidate` (ID `14764262871`). Contains the portable `approval-atomicity-upstream.patch`, proof it applies to a pristine checkout, logs, tool versions, and test results. Artifacts retain 14 days in GitHub Actions.
- Patch SHA-256: `d895dece6629c5440a5de81413273f421d78791c5f8d91280652919bfd90f979`, 17,796 bytes.
- Target Microsoft upstream revision: `f85abe1fffc5aaeed716a94bd6654677329215b9`, verified unchanged before patching.

## Scope

**Exactly five files changed** in the portable Git diff:

1. `agent-governance-python/agent-mesh/src/agentmesh/governance/approval_protocol/__init__.py`
2. `agent-governance-python/agent-mesh/src/agentmesh/governance/approval_protocol/coordinator.py`
3. `agent-governance-python/agent-mesh/src/agentmesh/governance/approval_protocol/store.py`
4. `agent-governance-python/agent-mesh/tests/test_approval_atomicity.py` (new)
5. `agent-governance-python/agent-mesh/tests/test_migration_contract.py` (new)

Diff summary: **338 insertions, 5 deletions** across the five files. The three production modules together account for **62 insertions and 5 deletions**. Separate edge-case and `govern()` integration test modules were run by the acceptance job but excluded from the portable patch to reduce review scope.

## Verified acceptance result

- Git `apply --check` and actual `git apply` against a separate pristine checkout succeeded.
- Full *source-built installation* of Microsoft Python core **5.0.0** and local Rust-backed ACS SDK **0.4.0b0** succeeded; the installed coordinator and `govern()` module were loaded from `site-packages`.
- Baseline without patch: sequential two-stage approval passed; both forced concurrent-stage regressions reproduced `chain_tampered` as intended.
- Patched source: **21/21** candidate research tests passed, with only two native modules included in the proposed patch.
- Expanded selected existing upstream approval, governance, and webhook tests: **168 passed, 11 skipped**.
- Rust-backed package installed and source lint/format checks passed; pre-existing upstream `UP035`/`UP045` typing deprecations were excluded from the lint gate.
- Multi-process SQLite research backend: **3/3** patched trials completed with valid chain.
- Deliberate worker-process termination: no partially committed vote survived; a new legitimate vote could proceed.
- Durable expiry: terminal `EXPIRED` resolution remained committed after late submission was rejected.

**Not tested:** full monorepo, real production database backend, arbitrary external approval transports, or performance under production workload. The SQLite fixture is research-authored; the forced race proves *possibility*, not prevalence. The observed original behavior fails closed and does not demonstrate a security bypass.

## Human review and submission blockers

The upstream [CONTRIBUTING.md](https://github.com/microsoft/agent-governance-toolkit/blob/main/CONTRIBUTING.md) expressly requires a human submitting AI-assisted code to understand and defend the exact changes and personally engage with maintainer feedback. Unreviewed autonomous PRs are not accepted by default.

The main open design choice is the migration contract: `AtomicApprovalStore` is optional; legacy third-party stores retain the race (with warnings), while strict mode requires transactional support. A database-wide SQLite lock was used for the test fixture; production backends need their own appropriate transaction design. The unrelated same-stage conflicting vote behavior is intentionally not changed.

**Before a PR:** the human owner must meaningfully review the patch, a real GitHub fork is required, a genuine DCO `Signed-off-by` commit is needed, and Microsoft CLA checks must be satisfied. We did not create a fork because the available connected GitHub actions do not support forking. No issue, PR, vulnerability disclosure, or maintainer contact was made.
