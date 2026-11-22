# Agent Effect Integrity — external conformance pilot

**Status:** research test harness, not a vulnerability report. All test subjects and effects are synthetic. The target is Microsoft's [Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit), Python `agentmesh` approval protocol.

## Target revision

`f85abe1fffc5aaeed716a94bd6654677329215b9` (pinned for reproducibility).

## What this runner tests

1. A changed action is rejected after approval. **Known upstream control.**
2. Concurrent execution validation allows a single approval consumer. **Protocol composition.**
3. Consuming an approval before a simulated crash and before any external effect leaves the approval consumed and effect unrecorded. **Expected contract boundary; no confirmed vulnerability.**

The third scenario does not demonstrate that the Microsoft project violates a security guarantee. It helps define integration responsibilities for effect reconciliation.

## Workflow and safeguards

The GitHub Actions workflow runs only on changes under this research directory on the dedicated research branch. It uses read-only repository permissions and no credentials, API keys, real-world services, or external actions. The runner pins the upstream repository commit, installs the documented core Python package, executes our tests plus a small upstream control suite, and uploads logs/artifacts if a run is produced.

A pass is evidence only of these synthetic tests on the pinned revision. Import errors and skipped target tests are not counted as passes. No GPU resources are used.

Source: `agent-governance-python/agent-mesh/src/agentmesh/governance/approval_protocol`.

## Next steps

Compare our observed outcome boundary with the documented contract and existing tests; determine whether a realistic integration-level test would contribute new value. Do not submit issues or claim defects based only on the consume-before-effect result.
