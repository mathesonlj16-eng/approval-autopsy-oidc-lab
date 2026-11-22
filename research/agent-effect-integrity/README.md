# Agent Effect Integrity — pinned-source conformance pilot

**Status:** reproducible research harness, not a vulnerability report. All actions and effects are synthetic.

The target is Microsoft's [Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit), Python `agentmesh` action-bound approval protocol at pinned revision `f85abe1fffc5aaeed716a94bd6654677329215b9`.

## Test coverage

- Changing the exact action after approval is denied (**already covered upstream**).
- Concurrent executions cannot consume the same approval more than once (**composition/control**).
- Consuming approval and then simulating a crash before the synthetic effect leaves no effect, and retry is denied (**expected protocol boundary; not a vulnerability finding**).

The CI runner also executes the original upstream `test_approval_protocol.py` file unchanged as a control.

## Reproduction and limitations

The first GitHub Actions attempt failed to install the full consolidated package because its declared `agent-control-specification>=0.4.0b0` dependency was not available from PyPI. That is an installation blocker, **not a security defect**.

The revised runner checks out the exact upstream commit and uses `research-support/agentmesh_protocol_bootstrap.py` to import only the original, unmodified approval-protocol package and its dependencies via standard Python imports, skipping the broad `agentmesh.governance` package initializer. Therefore the results apply to **the isolated protocol source**, not a fully installed or deployed Agent Governance Toolkit integration. We explicitly don't call skipped tests passes.

GitHub Actions permissions are read-only; tests use no credentials, production tools, external writes, hosted agents, or GPUs. Runs are bounded to 15 minutes. Test logs and environment details are uploaded as artifacts where possible.

## Next step

After successful tests, compare the observed boundary with the upstream guarantees and select a real integration-level contract to investigate. Do not file a vulnerability report based on this baseline alone.
